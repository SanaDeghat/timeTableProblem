import csv
import math
import random
import re
from collections import defaultdict
from ortools.sat.python import cp_model

from Student import Student
from Class import Class


NUM_BLOCKS = 8


def main():
    courses = load_courses("DataFiles/Course Tally.csv")
    students = load_students("DataFiles/cleanedstudentrequests.csv")
    blocking_rules = load_blocking_rules("DataFiles/Course Blocking Rules.csv")
    rooms = load_rooms("DataFiles/Staff list with rooms.csv")

    print_data_structures(courses, students)

    status, obj, course_block_index, assignment = solve(
        students, courses, blocking_rules, time_limit_s=30.0
    )
    print("Solve status:", status)
    print()

    sections, section_enrollments, section_rooms, room_conflicts, invalid_room_assignments = (
        assign_sections_and_rooms(students, courses, course_block_index, rooms, assignment)
    )

    print_master_preview(students, section_rooms, limit=25)
    export_master_csv(students, section_rooms, "master_timetable.csv")
    print("Exported master_timetable.csv\n")

    print_courses_by_block(students)

    metrics(
        students,
        courses,
        blocking_rules,
        course_block_index,
        sections,
        section_enrollments,
        room_conflicts,
        invalid_room_assignments,
        obj,
    )

    print_one_student(students, section_rooms, student_id=None)


def solve(students: list, courses: dict, blocking_rules: list, time_limit_s: float = 15.0):
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
                department="Unknown",
                requestedPrimary=0,
                requestedAlt=0,
                capacity=30,
                section=1,
            )

    course_codes = sorted(requested_codes)

    course_block = {}
    course_block_index = {}
    for code in course_codes:
        course_block_index[code] = model.NewIntVar(0, NUM_BLOCKS - 1, f"cblock_{code}")
        block_vars = []
        for b in range(NUM_BLOCKS):
            var = model.NewBoolVar(f"course_{code}_b{b}")
            course_block[(code, b)] = var
            block_vars.append(var)
        model.Add(sum(block_vars) == 1)
        model.Add(sum(b * course_block[(code, b)] for b in range(NUM_BLOCKS)) == course_block_index[code])

    x = {}
    for s, st in enumerate(students):
        course_flags = {c: False for c in st.requestedCourses}
        course_flags.update({c: True for c in st.alternateCourses})

        for b in range(NUM_BLOCKS):
            for c in course_flags:
                if c not in course_codes:
                    continue
                x[(s, c, b)] = model.NewBoolVar(f"x_s{s}_c{c}_b{b}")
                model.Add(x[(s, c, b)] <= course_block[(c, b)])

        for b in range(NUM_BLOCKS):
            model.Add(
                sum(x[(s, c, b)] for c in course_flags if (s, c, b) in x) <= 1
            )

        for c in course_flags:
            if c not in course_codes:
                continue
            model.Add(sum(x[(s, c, b)] for b in range(NUM_BLOCKS)) <= 1)

    # capacity and min-fill per course
    course_open = {}
    for code in course_codes:
        cap = courses[code].capacity if isinstance(courses[code].capacity, int) else 0
        sections = courses[code].section if isinstance(courses[code].section, int) else 0
        total_assigned = sum(
            x[(s, code, b)] for (s, c, b) in x if c == code
        )

        if sections <= 0:
            model.Add(total_assigned == 0)
            continue

        if cap <= 0:
            cap = 30

        max_total = cap * sections
        min_total = int(math.ceil(0.5 * cap)) * sections
        course_open[code] = model.NewBoolVar(f"open_{code}")
        model.Add(total_assigned <= max_total * course_open[code])
        model.Add(total_assigned >= min_total * course_open[code])

    # blocking rules
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
    for (s, c, b), var in x.items():
        is_alt = c in students[s].alternateCourses
        weight = 6 if is_alt else 10
        objective_terms.append(weight * var)

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("No feasible solution found.")

    assignment = defaultdict(list)
    for i, st in enumerate(students):
        st.assignedCourses = [None] * NUM_BLOCKS
        st.assignedSections = [None] * NUM_BLOCKS
        for b in range(NUM_BLOCKS):
            chosen = None
            for c in st.requestedCourses + st.alternateCourses:
                if (i, c, b) in x and solver.Value(x[(i, c, b)]) == 1:
                    chosen = c
                    break
            st.assignedCourses[b] = chosen
            if chosen is not None:
                assignment[chosen].append((st.id, b, i))

    course_block_index_value = {
        code: solver.Value(course_block_index[code]) for code in course_codes
    }

    return status, solver.ObjectiveValue(), course_block_index_value, assignment


def load_courses(course_csv_path: str):
    courses = {}

    def _to_int(value: str) -> int:
        value = (value or "").strip()
        if not value:
            return 0
        try:
            return int(float(value))
        except ValueError:
            return 0

    with open(course_csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 3:
                continue
            code = (row[1] or "").strip() if len(row) > 1 else ""
            description = (row[2] or "").strip() if len(row) > 2 else ""
            department = (row[3] or "").strip() if len(row) > 3 else ""

            if not code or "-" not in code or code.lower() == "number":
                continue

            if code not in courses:
                courses[code] = Class(
                    code=code,
                    name=description,
                    department=department,
                    requestedPrimary=_to_int(row[4] if len(row) > 4 else ""),
                    requestedAlt=_to_int(row[5] if len(row) > 5 else "") - _to_int(row[4] if len(row) > 4 else ""),
                    capacity=_to_int(row[6] if len(row) > 6 else ""),
                    section=_to_int(row[7] if len(row) > 7 else ""),
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
                    if alternate_col is not None and len(row) > alternate_col:
                        is_alt = (row[alternate_col] or "").strip().upper() == "Y"
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
        print("  assignedCourses_len:", len(s.assignedCourses))
        print("  alternateCourses_len:", len(s.alternateCourses))

    timetable = {st.id: [None] * NUM_BLOCKS for st in students}
    print(f"Timetable structure: dict[int, list[Optional[str]]], size={len(timetable)}")
    if students:
        sample_idx = 50 if len(students) > 50 else 0
        print("Timetable sample:", {students[sample_idx].id: timetable[students[sample_idx].id]})
    print()


def export_master_csv(students: list, section_rooms: dict, out_path: str):
    header = ["StudentID", "YOG"] + [f"Block{b+1}" for b in range(NUM_BLOCKS)]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for st in students:
            row = [st.id, st.yog]
            for b in range(NUM_BLOCKS):
                c = st.assignedCourses[b]
                sec = st.assignedSections[b]
                if c is None:
                    row.append("NULL")
                else:
                    room = section_rooms.get(sec, "") if sec is not None else ""
                    label = sec if sec is not None else f"{c}"
                    if room:
                        label = f"{label}@{room}"
                    row.append(label)
            w.writerow(row)


def print_master_preview(students: list, section_rooms: dict, limit: int = 25):
    print("=== Master Timetable (preview) ===")
    print("StudentID | YOG | " + " | ".join([f"B{b+1}" for b in range(NUM_BLOCKS)]))
    for st in students[:limit]:
        blocks = []
        for b in range(NUM_BLOCKS):
            c = st.assignedCourses[b]
            sec = st.assignedSections[b]
            if c is None:
                blocks.append("NULL")
            else:
                room = section_rooms.get(sec, "") if sec is not None else ""
                label = sec if sec is not None else f"{c}"
                if room:
                    label = f"{label}@{room}"
                blocks.append(label)
        blocks = " | ".join(blocks)
        print(f"{st.id} | {st.yog} | {blocks}")
    if len(students) > limit:
        print(f"... ({len(students) - limit} more students not shown)")
    print()


def print_courses_by_block(students: list):
    courses_by_block = {b: set() for b in range(NUM_BLOCKS)}
    
    for st in students:
        for b in range(NUM_BLOCKS):
            c = st.assignedCourses[b]
            if c is not None:
                course_name = c.getName() if hasattr(c, 'getName') else str(c)
                courses_by_block[b].add(course_name)
    
    for b in range(NUM_BLOCKS):
        courses = sorted(list(courses_by_block[b]))
       

    
    export_courses_by_block_csv(courses_by_block, "courses_by_block.csv")


def export_courses_by_block_csv(courses_by_block: dict, out_path: str):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        
        # Write header row with block names
        header = [f"Block {b+1}" for b in range(NUM_BLOCKS)]
        w.writerow(header)
        
        # Get sorted courses for each block
        all_block_courses = [sorted(list(courses_by_block[b])) for b in range(NUM_BLOCKS)]
        
        # Find max number of courses in any block
        max_courses = max(len(courses) for courses in all_block_courses) if all_block_courses else 0
        
        # Write each row with one course per column
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
    room_conflicts: int,
    invalid_room_assignments: int,
    objective_value: float,
):
    total_requests = sum(len(st.requestedCourses) for st in students)
    placed_requested = sum(
        1
        for st in students
        for c in st.assignedCourses
        if c is not None and c in st.requestedCourses
    )
    placed_total = sum(1 for st in students for c in st.assignedCourses if c is not None)
    unassigned_requests = total_requests - placed_requested

    pct_requests_placed = (placed_requested / total_requests * 100.0) if total_requests else 0.0

    full_requested = sum(
        1
        for st in students
        if sum(1 for c in st.assignedCourses if c is not None and c in st.requestedCourses) == NUM_BLOCKS
    )
    seven_plus_requested = sum(
        1
        for st in students
        if sum(1 for c in st.assignedCourses if c is not None and c in st.requestedCourses) >= 7
    )
    full_requested_or_alt = sum(
        1
        for st in students
        if sum(
            1
            for c in st.assignedCourses
            if c is not None and (c in st.requestedCourses or c in st.alternateCourses)
        )
        == NUM_BLOCKS
    )

    pct_full_requested = (full_requested / len(students) * 100.0) if students else 0.0
    pct_seven_plus_requested = (seven_plus_requested / len(students) * 100.0) if students else 0.0
    pct_full_requested_or_alt = (full_requested_or_alt / len(students) * 100.0) if students else 0.0

    student_conflicts = 0
    for st in students:
        seen = set()
        for c in st.assignedCourses:
            if c is None:
                continue
            if c in seen:
                student_conflicts += 1
            seen.add(c)

    # Enrollment metrics
    section_counts = len(sections)
    full_sections = 0
    half_empty_sections = 0
    for sec_id, sec_info in sections.items():
        enrolled = len(section_enrollments.get(sec_id, []))
        cap = sec_info["capacity"]
        if cap > 0 and enrolled >= cap:
            full_sections += 1
        if cap > 0 and enrolled < 0.5 * cap:
            half_empty_sections += 1

    # Distribution across blocks
    classes_per_block = [0] * NUM_BLOCKS
    for sec in sections.values():
        b = sec["block"]
        if 0 <= b < NUM_BLOCKS:
            classes_per_block[b] += 1

    # Blocking rules success
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

    print("=== Student Metrics ===")
    print(f"% of requests placed: {pct_requests_placed:.2f}%")
    print(f"% students with 8/8 requested: {pct_full_requested:.2f}%")
    print(f"% students with 7-8/8 requested: {pct_seven_plus_requested:.2f}%")
    print(f"% students with 8/8 requested or alternate: {pct_full_requested_or_alt:.2f}%")
    print("Student timetable conflicts:", student_conflicts)
    print("Unassigned course requests:", unassigned_requests)
    print()

    print("=== Enrollment Metrics ===")
    print("Total sections:", section_counts)
    print("Full sections:", full_sections)
    print("Sections < 50% enrollment:", half_empty_sections)
    print("Enrollment by section:")
    for sec_id, sec_info in sorted(sections.items()):
        enrolled = len(section_enrollments.get(sec_id, []))
        print(
            f"  {sec_id} ({sec_info['course']}, block {sec_info['block'] + 1}): {enrolled}"
        )
    print()

    print("=== Timetable Metrics ===")
    print("Room conflicts:", room_conflicts)
    print("Invalid room assignments:", invalid_room_assignments)
    print("Distribution of classes across blocks:", classes_per_block)
    print(f"% blocking rules satisfied: {pct_blocking:.2f}%")
    print("Optimization objective (solver):", objective_value)
    print()


def print_one_student(students: list, section_rooms: dict, student_id=None):
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
    print(f"Student {st.id} (YOG {st.yog})")
    for b in range(NUM_BLOCKS):
        c = st.assignedCourses[b]
        sec = st.assignedSections[b]
        if c is None:
            display = "NULL"
        else:
            room = section_rooms.get(sec, "") if sec is not None else ""
            display = sec if sec is not None else f"{c}"
            if room:
                display = f"{display}@{room}"
        print(f"  Block {b+1}: {display}")
    print()


def normalize_text(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


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

            if "Simultaneous" in text:
                rule_type = "Simultaneous"
            elif "NotSimultaneous" in text:
                rule_type = "NotSimultaneous"
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

    for code, course in courses.items():
        if code not in course_block_index:
            continue
        section_count = course.section if isinstance(course.section, int) else 0
        cap = course.capacity if isinstance(course.capacity, int) else 0
        for idx in range(1, max(section_count, 0) + 1):
            sec_id = f"S{idx}"
            sections[f"{code}-{sec_id}"] = {
                "course": code,
                "section": sec_id,
                "capacity": cap,
                "block": course_block_index[code],
            }

    # assign students to sections
    for code, entries in assignment.items():
        sec_ids = [sid for sid, s in sections.items() if s["course"] == code]
        if not sec_ids:
            continue
        sec_ids.sort()

        for i, (student_id, block, student_idx) in enumerate(entries):
            sec_id = sec_ids[i % len(sec_ids)]
            section_enrollments[sec_id].append(student_id)
            students[student_idx].assignedSections[block] = sec_id

    # assign rooms
    rooms_by_dept = defaultdict(list)
    for room in rooms:
        rooms_by_dept[room["department"]].append(room["room"])

    open_rooms = rooms_by_dept.get("Open", [])
    used_by_block = {b: set() for b in range(NUM_BLOCKS)}
    section_rooms = {}
    room_conflicts = 0
    invalid_room_assignments = 0

    sections_by_block = defaultdict(list)
    for sec_id, info in sections.items():
        sections_by_block[info["block"]].append(sec_id)

    for b, sec_ids in sections_by_block.items():
        for sec_id in sec_ids:
            course_code = sections[sec_id]["course"]
            dept = courses[course_code].department if course_code in courses else ""
            room = None

            for candidate in rooms_by_dept.get(dept, []):
                if candidate not in used_by_block[b]:
                    room = candidate
                    break
            if room is None:
                for candidate in open_rooms:
                    if candidate not in used_by_block[b]:
                        room = candidate
                        break
            if room is None:
                for candidate in [r["room"] for r in rooms]:
                    if candidate not in used_by_block[b]:
                        room = candidate
                        break

            if room is None:
                room_conflicts += 1
                room = "TBD"
            else:
                used_by_block[b].add(room)

            section_rooms[sec_id] = room
            room_dept = None
            for r in rooms:
                if r["room"] == room:
                    room_dept = r["department"]
                    break
            if room_dept and room_dept != dept and room_dept != "Open":
                invalid_room_assignments += 1

    return sections, section_enrollments, section_rooms, room_conflicts, invalid_room_assignments


if __name__ == "__main__":
    main()