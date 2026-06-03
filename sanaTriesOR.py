import csv
import math
import random
import re
from collections import Counter, defaultdict

from ortools.sat.python import cp_model

from Student import Student
from Class import Class


NUM_BLOCKS = 8
SMALL_CAPACITY_KEYWORDS = (
    "science",
    "physics",
    "chem",
    "lab",
    "auto",
    "automotive",
    "wood",
    "robot",
    "robotics",
    "comp sci",
    "computer science",
    "computer programming",
)


def main():
    courses = load_courses("DataFiles/Course Number of Sections.csv")
    students = load_students("DataFiles/cleanedstudentrequests.csv")
    blocking_rules = load_blocking_rules("DataFiles/course Simultaneous Blocking.csv")
    rooms = load_rooms("DataFiles/Staff list with rooms.csv")

    print_data_structures(courses, students)

    status, obj, course_block_index, assignment = solve(
        students,
        courses,
        blocking_rules,
        time_limit_s=30.00,
    )
    print("Solve status:", status)
    print()

    (
        sections,
        section_enrollments,
        section_rooms,
        room_conflicts,
        invalid_room_assignments,
        overfilled_sections,
        underfilled_sections,
    ) = assign_sections_and_rooms(students, courses, course_block_index, rooms, assignment)

    print_master_preview(students, courses, section_rooms, limit=25)
    export_master_csv(students, courses, section_rooms, "master_timetable.csv")
    print("Exported master_timetable.csv\n")

    print_courses_by_block(students, courses)

    metrics(
        students,
        courses,
        blocking_rules,
        course_block_index,
        sections,
        section_enrollments,
        section_rooms,
        room_conflicts,
        invalid_room_assignments,
        overfilled_sections,
        underfilled_sections,
        obj,
    )

    print_one_student(students, courses, section_rooms, student_id=None)


def solve(
    students: list,
    courses: dict,
    blocking_rules: list,
    time_limit_s: float = 5.00,
):
    model = cp_model.CpModel()

    requested_codes = set()
    for st in students:
        requested_codes.update(st.requestedCourses)
        requested_codes.update(st.alternateCourses)

    for code in list(requested_codes):
        if code not in courses:
            courses[code] = Class(
                code=code,
                name=code,
                department=infer_department(code, code),
                requestedPrimary=0,
                requestedAlt=0,
                capacity=max_capacity_for_course(code, code),
                section=1,
            )

    course_codes = sorted(requested_codes)

    course_block = {}
    course_block_index = {}
    for code in course_codes:
        course_block_index[code] = model.NewIntVar(0, NUM_BLOCKS - 1, f"cblock_{code}")
        bvars = []
        for b in range(NUM_BLOCKS):
            var = model.NewBoolVar(f"course_{code}_b{b}")
            course_block[(code, b)] = var
            bvars.append(var)
        model.Add(sum(bvars) == 1)
        model.Add(sum(b * course_block[(code, b)] for b in range(NUM_BLOCKS)) == course_block_index[code])

    x = {}
    for s, st in enumerate(students):
        all_choices = list(dict.fromkeys(st.requestedCourses + st.alternateCourses))

        for b in range(NUM_BLOCKS):
            for c in all_choices:
                if c not in course_codes:
                    continue
                x[(s, c, b)] = model.NewBoolVar(f"x_s{s}_c{c}_b{b}")
                model.Add(x[(s, c, b)] <= course_block[(c, b)])

        for b in range(NUM_BLOCKS):
            model.Add(sum(x[(s, c, b)] for c in all_choices if (s, c, b) in x) <= 1)

        for c in all_choices:
            if c not in course_codes:
                continue
            model.Add(sum(x[(s, c, b)] for b in range(NUM_BLOCKS)) <= 1)

    # Enrollment bounds at course level, derived from section counts and per-section limits.
    for code in course_codes:
        cap = courses[code].capacity if isinstance(courses[code].capacity, int) and courses[code].capacity > 0 else 30
        sections = courses[code].section if isinstance(courses[code].section, int) and courses[code].section > 0 else 1
        total_assigned = sum(x[(s, code, b)] for (s, c, b) in x if c == code)

        max_total = cap * sections
        min_total = int(math.ceil(0.5 * cap)) * sections

        course_runs = model.NewBoolVar(f"course_runs_{code}")
        model.Add(total_assigned <= max_total * course_runs)
        model.Add(total_assigned >= min_total * course_runs)

    # Blocking rules from CSV.
    for rule in blocking_rules:
        rule_courses = [c for c in rule["courses"] if c in course_codes]
        if len(rule_courses) < 2:
            continue

        if rule["type"] == "Simultaneous":
            base = rule_courses[0]
            for other in rule_courses[1:]:
                model.Add(course_block_index[base] == course_block_index[other])

        elif rule["type"] == "NotSimultaneous":
            for i in range(len(rule_courses)):
                for j in range(i + 1, len(rule_courses)):
                    c1 = rule_courses[i]
                    c2 = rule_courses[j]
                    for b in range(NUM_BLOCKS):
                        model.Add(course_block[(c1, b)] + course_block[(c2, b)] <= 1)

        elif rule["type"] == "Consecutive":
            for i in range(len(rule_courses) - 1):
                c1 = rule_courses[i]
                c2 = rule_courses[i + 1]
                delta = model.NewIntVar(0, NUM_BLOCKS - 1, f"delta_{c1}_{c2}")
                model.AddAbsEquality(delta, course_block_index[c1] - course_block_index[c2])
                model.Add(delta == 1)

    objective_terms = []
    for (s, c, _b), var in x.items():
        is_alt = c in students[s].alternateCourses
        weight = 6 if is_alt else 10
        objective_terms.append(weight * var)

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    if isinstance(time_limit_s, (int, float)) and time_limit_s > 0:
        solver.parameters.max_time_in_seconds = float(time_limit_s)
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("No feasible solution found.")

    assignment = defaultdict(list)
    for i, st in enumerate(students):
        st.assignedCourses = [None] * NUM_BLOCKS
        st.assignedSections = [None] * NUM_BLOCKS

        all_choices = list(dict.fromkeys(st.requestedCourses + st.alternateCourses))
        for b in range(NUM_BLOCKS):
            chosen = None
            for c in all_choices:
                if (i, c, b) in x and solver.Value(x[(i, c, b)]) == 1:
                    chosen = c
                    break
            st.assignedCourses[b] = chosen
            if chosen is not None:
                assignment[chosen].append((st.id, b, i))

    course_block_index_value = {code: solver.Value(course_block_index[code]) for code in course_codes}
    return status, solver.ObjectiveValue(), course_block_index_value, assignment


def load_course_sections(sections_csv_path: str) -> dict:
    sections = {}

    def _to_int(value: str) -> int:
        try:
            return int(float((value or "").strip()))
        except Exception:
            return 0

    with open(sections_csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 3:
                continue

            code = (row[1] or "").strip() if len(row) > 1 else ""
            description = (row[2] or "").strip() if len(row) > 2 else ""
            if not code or "-" not in code or code.lower() == "course":
                continue

            sec = _to_int(row[4]) if len(row) > 4 else 0
            if sec <= 0:
                sec = 1

            sections[code] = (sec, description)

    return sections


def load_courses(course_csv_path: str):
    courses = {}
    sections_map = load_course_sections(course_csv_path)

    for code, (section_count, description) in sections_map.items():
        per_section_capacity = max_capacity_for_course(code, description)
        department = infer_department(code, description)

        courses[code] = Class(
            code=code,
            name=description,
            department=department,
            requestedPrimary=0,
            requestedAlt=0,
            capacity=per_section_capacity,
            section=max(1, int(section_count)),
        )

    return courses


def load_students(student_csv_path: str):
    students = []
    with open(student_csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        current_student_id = None
        current_grade = None
        current_courses = []
        current_alternates = []
        alternate_col = None

        for row in reader:
            if not row or len(row) < 2:
                continue

            if row[0] == "ID":
                if current_student_id is not None:
                    students.append(
                        Student(
                            current_student_id,
                            current_grade,
                            current_courses,
                            alternateCourses=current_alternates,
                        )
                    )
                    current_courses = []
                    current_alternates = []

                current_student_id = row[1].strip() if len(row) > 1 else None
                current_grade = row[3].strip() if len(row) > 3 else None
                alternate_col = None
                continue

            if row[0] == "Course":
                alternate_col = None
                for idx, val in enumerate(row):
                    if (val or "").strip().lower() == "alternate":
                        alternate_col = idx 
                        break
                continue

            if current_student_id is not None and row[0].strip():
                course_code = row[0].strip()
                if "-" in course_code and course_code.upper() != "COURSE":
                    is_alt = False
                    if alternate_col is not None:
                        for idx in (alternate_col, alternate_col + 1, alternate_col - 1):
                            if idx is not None and 0 <= idx < len(row) and (row[idx] or "").strip().upper() == "Y":
                                is_alt = True
                                break
                    else:
                        # Fallback: scan the tail of the row for a 'Y' flag (robust to misaligned CSV columns)
                        for cell in row[7: max(8, len(row) - 1)]:
                            if (cell or "").strip().upper() == "Y":
                                is_alt = True
                                break

                    if is_alt:
                        current_alternates.append(course_code)
                    else:
                        current_courses.append(course_code)

        if current_student_id is not None:
            students.append(
                Student(
                    current_student_id,
                    current_grade,
                    current_courses,
                    alternateCourses=current_alternates,
                )
            )

    return students


def print_data_structures(courses: dict, students: list):
    print("data")
    print(f"Courses structure: dict[str, Class], size={len(courses)}")
    if courses:
        first_key = next(iter(courses))
        print("Course sample key:", first_key)
        print("Course sample value:", courses[first_key])

    print(f"Students structure: list[Student], size={len(students)}")
    if students:
        s = students[0]
        print("Student sample:", s)
        print("  requestedCourses_len:", len(s.requestedCourses))
        print("  requestedCourses_first_5:", s.requestedCourses[:5])
        print("  alternateCourses_len:", len(s.alternateCourses))
        print("  assignedCourses_len:", len(s.assignedCourses))

    timetable = {st.id: [None] * NUM_BLOCKS for st in students}
    print(f"Timetable structure: dict[int, list[Optional[str]]], size={len(timetable)}")
    if students:
        sample_idx = 50 if len(students) > 50 else 0
        print("Timetable sample:", {students[sample_idx].id: timetable[students[sample_idx].id]})
    print()


def export_master_csv(students: list, courses: dict, section_rooms: dict, out_path: str):
    header = ["StudentID", "currentGrade"] + [f"Block{b+1}" for b in range(NUM_BLOCKS)]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for st in students:
            row = [st.id, st.currentGrade]
            for b in range(NUM_BLOCKS):
                code = st.assignedCourses[b]
                section_id = st.assignedSections[b]
                if code is None:
                    row.append("NULL")
                else:
                    name = courses[code].getName() if code in courses else code
                    room = section_rooms.get(section_id, "") if section_id else ""
                    if section_id:
                        label = f"{name} ({section_id})"
                    else:
                        label = name
                    if room:
                        label = f"{label} @ {room}"
                    row.append(label)
            w.writerow(row)


def print_master_preview(students: list, courses: dict, section_rooms: dict, limit: int = 25):
    print("=== Master Timetable (preview) ===")
    print("StudentID | currentGrade | " + " | ".join([f"B{b+1}" for b in range(NUM_BLOCKS)]))
    for st in students[:limit]:
        blocks = []
        for b in range(NUM_BLOCKS):
            code = st.assignedCourses[b]
            section_id = st.assignedSections[b]
            if code is None:
                blocks.append("NULL")
                continue
            name = courses[code].getName() if code in courses else code
            room = section_rooms.get(section_id, "") if section_id else ""
            value = f"{name} ({section_id})" if section_id else name
            if room:
                value = f"{value} @ {room}"
            blocks.append(value)
        print(f"{st.id} | {st.currentGrade} | " + " | ".join(blocks))
    if len(students) > limit:
        print(f"... ({len(students) - limit} more students not shown)")
    print()


def print_courses_by_block(students: list, courses: dict):
    courses_by_block = {b: set() for b in range(NUM_BLOCKS)}

    for st in students:
        for b in range(NUM_BLOCKS):
            code = st.assignedCourses[b]
            if code is not None:
                name = courses[code].getName() if code in courses else str(code)
                courses_by_block[b].add(name)

    export_courses_by_block_csv(courses_by_block, "courses_by_block.csv")


def export_courses_by_block_csv(courses_by_block: dict, out_path: str):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = [f"Block {b+1}" for b in range(NUM_BLOCKS)]
        w.writerow(header)

        all_block_courses = [sorted(list(courses_by_block[b])) for b in range(NUM_BLOCKS)]
        max_courses = max(len(courses) for courses in all_block_courses) if all_block_courses else 0

        for row_idx in range(max_courses):
            row = []
            for b in range(NUM_BLOCKS):
                if row_idx < len(all_block_courses[b]):
                    row.append(all_block_courses[b][row_idx])
                else:
                    row.append("")
            w.writerow(row)

    print(f"Exported {out_path}\n")


def metrics(
    students: list,
    courses: dict,
    blocking_rules: list,
    course_block_index: dict,
    sections: dict,
    section_enrollments: dict,
    section_rooms: dict,
    room_conflicts: int,
    invalid_room_assignments: int,
    overfilled_sections: int,
    underfilled_sections: int,
    objective_value: float,
):
    total_students = len(students)

    total_requests = sum(len(st.requestedCourses) for st in students)
    placed_requested = sum(
        1
        for st in students
        for c in st.assignedCourses
        if c is not None and c in st.requestedCourses
    )
    unassigned_requests = max(0, total_requests - placed_requested)

    pct_requests_placed = (placed_requested / total_requests * 100.0) if total_requests else 0.0

    full_requested = 0
    seven_plus_requested = 0
    full_requested_or_alt = 0
    perfect_requested_students = []

    for st in students:
        req_hits = sum(1 for c in st.assignedCourses if c is not None and c in st.requestedCourses)
        any_hits = sum(
            1
            for c in st.assignedCourses
            if c is not None and (c in st.requestedCourses or c in st.alternateCourses)
        )

        if req_hits == NUM_BLOCKS:
            full_requested += 1
            perfect_requested_students.append(st.id)
        if req_hits >= NUM_BLOCKS - 1:
            seven_plus_requested += 1
        if any_hits == NUM_BLOCKS:
            full_requested_or_alt += 1

    pct_full_requested = (full_requested / total_students * 100.0) if total_students else 0.0
    pct_seven_plus_requested = (seven_plus_requested / total_students * 100.0) if total_students else 0.0
    pct_full_requested_or_alt = (full_requested_or_alt / total_students * 100.0) if total_students else 0.0

    students_with_timetable_conflicts = 0
    student_conflicts = 0
    for st in students:
        non_null = [c for c in st.assignedCourses if c is not None]
        duplicates = sum(v - 1 for v in Counter(non_null).values() if v > 1)
        if duplicates > 0:
            students_with_timetable_conflicts += 1
            student_conflicts += duplicates

    section_counts = len(sections)
    full_sections = 0
    half_empty_sections = 0

    for sec_id, sec_info in sections.items():
        enrolled = len(section_enrollments.get(sec_id, []))
        cap = sec_info["capacity"]
        if cap > 0 and enrolled >= cap:
            full_sections += 1
        if cap > 0 and enrolled < math.ceil(0.5 * cap):
            half_empty_sections += 1

    classes_per_block = [0] * NUM_BLOCKS
    for sec in sections.values():
        b = sec["block"]
        if 0 <= b < NUM_BLOCKS:
            classes_per_block[b] += 1

    applicable = 0
    satisfied = 0
    for rule in blocking_rules:
        rule_courses = [c for c in rule["courses"] if c in course_block_index]
        if len(rule_courses) < 2:
            continue

        applicable += 1
        if rule["type"] == "Simultaneous":
            blocks = {course_block_index[c] for c in rule_courses}
            if len(blocks) == 1:
                satisfied += 1

        elif rule["type"] == "NotSimultaneous":
            blocks = [course_block_index[c] for c in rule_courses]
            if len(blocks) == len(set(blocks)):
                satisfied += 1

        elif rule["type"] == "Consecutive":
            ok = True
            for i in range(len(rule_courses) - 1):
                if abs(course_block_index[rule_courses[i]] - course_block_index[rule_courses[i + 1]]) != 1:
                    ok = False
                    break
            if ok:
                satisfied += 1

    pct_blocking = (satisfied / applicable * 100.0) if applicable else 0.0

    # Enrollment detail report (students in each section).
    print("=== Enrollment By Section ===")
    for sec_id in sorted(sections.keys()):
        info = sections[sec_id]
        enrolled = len(section_enrollments.get(sec_id, []))
        room = section_rooms.get(sec_id, "TBD")
        code = info["course"]
        name = courses[code].getName() if code in courses else code
        print(
            f"{code} {name} | Section {info['section']} | Block {info['block'] + 1} | "
            f"Room {room} | Enrollment {enrolled}/{info['capacity']}"
        )
    print()

    score_requested_placed = placed_requested * 10
    score_full_timetables = full_requested_or_alt * 50
    score_room_conflicts = -1000 * room_conflicts
    score_student_conflicts = -1000 * student_conflicts
    score_invalid_room = -500 * invalid_room_assignments
    score_overfilled = -1000 * overfilled_sections
    total_sections = sum(classes_per_block)
    avg_per_block = (total_sections / NUM_BLOCKS) if NUM_BLOCKS else 0
    lower = math.floor(avg_per_block)
    upper = math.ceil(avg_per_block)
    score_balanced = sum(count for count in classes_per_block if lower <= count <= upper)

    total_score = (
        score_requested_placed
        + score_full_timetables
        + score_room_conflicts
        + score_student_conflicts
        + score_invalid_room
        + score_overfilled
        + score_balanced
    )

    print("=== Student Metrics ===")
    print(f"% of all requests successfully placed: {pct_requests_placed:.2f}% ({placed_requested}/{total_requests})")
    print(f"% of students with 8/8 requested courses: {pct_full_requested:.2f}% ({full_requested}/{total_students})")
    print(f"% of students with 7-8/8 requested courses: {pct_seven_plus_requested:.2f}% ({seven_plus_requested}/{total_students})")
    print(
        f"% of students with 8/8 courses (requested or alternate): "
        f"{pct_full_requested_or_alt:.2f}% ({full_requested_or_alt}/{total_students})"
    )
    print(f"Number of students with timetable conflicts: {students_with_timetable_conflicts}")
    print(f"Number of unassigned course requests: {unassigned_requests}")
    print()

    print("=== Enrollment Metrics ===")
    print(f"Total number of sections: {section_counts}")
    print(f"Number of full sections: {full_sections}")
    print(f"Number of sections with less than 50% enrollment: {half_empty_sections}")
    print()

    print("=== Timetable Metrics ===")
    print(f"Number of room conflicts: {room_conflicts}")
    print(f"Number of student conflicts: {student_conflicts}")
    print(f"Number of invalid room assignments: {invalid_room_assignments}")
    print(f"Distribution of classes across blocks (courses per block): {classes_per_block}")
    print(f"% of blocking rules successfully implemented: {pct_blocking:.2f}% ({satisfied}/{applicable})")
    print(f"Overfilled sections: {overfilled_sections}")
    print(f"Sections below 50%: {underfilled_sections}")
    print(f"Optimization objective (solver): {objective_value}")
    print(f"Optimization Score: {total_score}")
    print()

    bonus_ids = perfect_requested_students[:3]
    if bonus_ids:
        print("=== Bonus: Sample Students With 8/8 Requested (No Alternate Needed) ===")
        print("Student IDs:", ", ".join(str(sid) for sid in bonus_ids))
        print()


def print_one_student(students: list, courses: dict, section_rooms: dict, student_id=None):
    if not students:
        print("No students.")
        return

    if student_id is None:
        st = random.choice(students)
    else:
        matches = [s for s in students if int(s.id) == int(student_id)]
        if not matches:
            print("Student not found:", student_id)
            return
        st = matches[0]

    print("=== Full timetable for one student ===")
    print(f"Student {st.id} (grade {st.currentGrade})")
    for b in range(NUM_BLOCKS):
        code = st.assignedCourses[b]
        section_id = st.assignedSections[b]
        if code is None:
            display = "NULL"
        else:
            name = courses[code].getName() if code in courses else code
            room = section_rooms.get(section_id, "") if section_id else ""
            display = f"{name} ({section_id})" if section_id else name
            if room:
                display = f"{display} @ {room}"
        print(f"  Block {b+1}: {display}")
    print()


def normalize_text(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def max_capacity_for_course(code: str, description: str) -> int:
    normalized = normalize_text(f"{code} {description}")
    if any(keyword in normalized for keyword in SMALL_CAPACITY_KEYWORDS):
        return 24
    return 30


def infer_department(code: str, description: str) -> str:
    t = normalize_text(f"{code} {description}")

    mapping = [
        ("wood", "Woodwork"),
        ("auto", "Automotive"),
        ("automotive", "Automotive"),
        ("robot", "Robotics"),
        ("draft", "Drafting"),
        ("physics", "Science"),
        ("chem", "Science"),
        ("science", "Science"),
        ("math", "Mathematics"),
        ("calculus", "Mathematics"),
        ("pre calculus", "Mathematics"),
        ("computer science", "Computer Lab"),
        ("computer programming", "CS/Yearbook"),
        ("media", "IT/3D Animation/Media"),
        ("animation", "IT/3D Animation/Media"),
        ("photo", "Photography"),
        ("art", "Art"),
        ("music", "Music"),
        ("band", "Music"),
        ("choir", "Music"),
        ("guitar", "Music"),
        ("pe", "PE"),
        ("active living", "PE"),
        ("dance", "Dance"),
        ("social", "Social Studies"),
        ("history", "Social Studies"),
        ("english", "English"),
        ("food", "Home Economics"),
        ("psychology", "Social Studies"),
    ]

    for key, dept in mapping:
        if key in t:
            return dept

    return "Open"


def load_rooms(rooms_csv_path: str):
    rooms = []
    with open(rooms_csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            room_id = (row.get("Num") or "").strip()
            dept = (row.get("Department") or "").strip()
            if room_id:
                rooms.append({"room": room_id, "department": dept})
    return rooms


def load_blocking_rules(blocking_csv_path: str):
    rules = []
    with open(blocking_csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            text = " ".join((cell or "").strip() for cell in row if cell)
            if "Schedule" not in text or "blocking" not in text:
                continue

            if "NotSimultaneous" in text:
                rule_type = "NotSimultaneous"
            elif "Simultaneous" in text:
                rule_type = "Simultaneous"
            elif "Consecutive" in text:
                rule_type = "Consecutive"
            else:
                continue

            start = text.find("Schedule") + len("Schedule")
            end = text.find(" in a")
            if end == -1:
                end = text.find(" blocking")
            course_part = text[start:end].strip()
            courses = [c.strip() for c in course_part.split(",") if c.strip()]
            if len(courses) >= 2:
                rules.append({"type": rule_type, "courses": courses})

    return rules


def assign_sections_and_rooms(students, courses, course_block_index, rooms, assignment):
    sections = {}
    section_enrollments = defaultdict(list)

    active_codes = {code for code, entries in assignment.items() if entries}

    for code in sorted(active_codes):
        if code not in courses or code not in course_block_index:
            continue

        course = courses[code]

        section_count = course.section if isinstance(course.section, int) and course.section > 0 else 1
        cap = course.capacity if isinstance(course.capacity, int) and course.capacity > 0 else 30

        for idx in range(1, section_count + 1):
            sec_name = f"S{idx}"
            sec_id = f"{code}-{sec_name}"
            sections[sec_id] = {
                "course": code,
                "section": sec_name,
                "capacity": cap,
                "block": course_block_index[code],
                "department": course.department,
            }

    # Assign students to sections round-robin so each section gets similar enrollment.
    for code, entries in assignment.items():
        sec_ids = sorted([sid for sid, info in sections.items() if info["course"] == code])
        if not sec_ids:
            continue

        for i, (student_id, block, student_idx) in enumerate(entries):
            sec_id = sec_ids[i % len(sec_ids)]
            section_enrollments[sec_id].append(student_id)
            students[student_idx].assignedSections[block] = sec_id

    rooms_by_dept = defaultdict(list)
    all_rooms = []
    for room in rooms:
        rooms_by_dept[room["department"]].append(room["room"])
        all_rooms.append(room["room"])

    open_rooms = rooms_by_dept.get("Open", [])
    used_by_block = {b: set() for b in range(NUM_BLOCKS)}

    section_rooms = {}
    room_conflicts = 0
    invalid_room_assignments = 0

    sections_by_block = defaultdict(list)
    for sec_id, info in sections.items():
        sections_by_block[info["block"]].append(sec_id)

    for b, sec_ids in sections_by_block.items():
        for sec_id in sorted(sec_ids):
            dept = sections[sec_id]["department"]
            selected = None

            for candidate in rooms_by_dept.get(dept, []):
                if candidate not in used_by_block[b]:
                    selected = candidate
                    break

            if selected is None:
                for candidate in open_rooms:
                    if candidate not in used_by_block[b]:
                        selected = candidate
                        break

            if selected is None:
                for candidate in all_rooms:
                    if candidate not in used_by_block[b]:
                        selected = candidate
                        break

            if selected is None:
                selected = "TBD"
                room_conflicts += 1
            else:
                used_by_block[b].add(selected)

            section_rooms[sec_id] = selected

            if selected != "TBD":
                assigned_room_dept = None
                for r in rooms:
                    if r["room"] == selected:
                        assigned_room_dept = r["department"]
                        break

                if assigned_room_dept and assigned_room_dept != "Open" and assigned_room_dept != dept:
                    invalid_room_assignments += 1

    overfilled_sections = 0
    underfilled_sections = 0
    for sec_id, info in sections.items():
        enrolled = len(section_enrollments.get(sec_id, []))
        cap = info["capacity"]
        if cap > 0 and enrolled > cap:
            overfilled_sections += 1
        if cap > 0 and enrolled < math.ceil(0.5 * cap):
            underfilled_sections += 1

    return (
        sections,
        section_enrollments,
        section_rooms,
        room_conflicts,
        invalid_room_assignments,
        overfilled_sections,
        underfilled_sections,
    )


if __name__ == "__main__":
    main()
