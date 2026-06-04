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

# Courses containing any of these keywords will be excluded from the master timetable
OUT_OF_TIMETABLE_KEYWORDS = (
    "peer",
    "tutoring",
    "yearbook",
    "leadership",
    "co-op",
    "coop",
    "study",
    "resource",
    "off timetable",
    "off-timetable",
    "YED--2DX-L",
    "linear",
    "YLRA-2AX-L",
    "CONCERT",
    "LRA-0AX-L",
    "YLRA-2AX-L",
    "YLRA-0AX-L",
    "YCPA-1AX-L",
    "YLRA-0AX-L",
    "YLRA-1AX-L",
    "XBA--09J-L",
    "MDNC-12--L",
    "MDNCM12--L",
    "XBA--09C-L",
    "XBA--09C-L"
    "XBA--09J-L",
    "YLRA-2AX-L",
    "YCPA-1AX-L",
    "XC---09--L",
    "XLDCB09S-L",
    "YED--2DX-L",
    "YED--0BX-L",
    "YCPA-2AX-L",
    "JAZZ"
)



def main():
    courses = load_courses("DataFiles/Course Number of Sections.csv")
    students = load_students("DataFiles/cleanedstudentrequests.csv")
    blocking_rules = load_blocking_rules("DataFiles/course Simultaneous Blocking.csv")
    rooms = load_rooms("DataFiles/Staff list with rooms.csv")

    # print_data_structures(courses, students)

    status, obj, course_block_index, assignment = solve(
        students,
        courses,
        blocking_rules,
        time_limit_s=60.00,
    )
    # print("Solve status:", status)
    # print()


    (
        sections,
        section_enrollments,
        section_rooms,
        room_conflicts,
        invalid_room_assignments,
        overfilled_sections,
        underfilled_sections,
    ) = assign_sections_and_rooms(students, courses, course_block_index, rooms, assignment)

    # Export student-level timetables to a distinct file.
    export_master_csv(students, courses, section_rooms, "every_students_timetable.csv")
    print("Exported every_students_timetable.csv\n")

    # Export course-by-block master timetable (sections + rooms) to master_timetable.csv
    export_master_by_block_csv(
        sections,
        courses,
        section_rooms,
        section_enrollments,
        "master_timetable.csv",
    )

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

    print_students_with_full_requested(students, courses, section_rooms, count=3)

    print(section_rooms)


def solve(
    students: list,
    courses: dict,
    blocking_rules: list,
    outside_timetable_courses: set | None = None,
    time_limit_s: float = 5.0,
):
    model = cp_model.CpModel()

    timetables = {}
    course_in_block = {}

    # creates variables
    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            course = student.requestedCourses
            for c in course:
                timetables[(s, b, c)] = model.NewBoolVar(f"table_s{s}_b{b}_c{c}")

    for c in courses:
        for b in range(NUM_BLOCKS):
            course_in_block[(c, b)] = model.NewBoolVar(f"course_{c}_block_{b}")


    # constraint 1: student dosent have more than 1 course per block
    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            model.AddAtMostOne(timetables[(s, b, c)] for c in student.requestedCourses)

    # constraint 2: course cant appear more than once
    for s, student in enumerate(students):
        for c in student.requestedCourses:
            model.AddAtMostOne(timetables[(s, b, c)] for b in range(NUM_BLOCKS))
   
    # constraint 3: limit number of sections per course
    for c, course_obj in courses.items():
        max_sections = course_obj.section
        model.Add(
            sum(course_in_block[(c, b)] for b in range(NUM_BLOCKS)) <= max_sections
        )

    for c in courses:
        for b in range(NUM_BLOCKS):
            enroled = sum(timetables[(s, b, c)]
                            for s, student in enumerate(students)
                            if c in student.requestedCourses
                        )      
            # constraint 4: no more than the max # of students per block(only enforces if the course is in the block)
            model.Add(enroled <= courses[c].capacity * course_in_block[(c, b)])

            # constraint 5: no less than 50% of a class(only enforces if the course is in the block)
            model.Add(enroled >= (int) (courses[c].capacity / 2) * course_in_block[(c, b)])

    # constraint 6: follows blocking rules
    for x in blocking_rules:

        # courses happen at the same time
        if x["type"] == "Simultaneous":
            base = x["courses"][0]
            for other in x["courses"][1:]:
                for b in range(NUM_BLOCKS):
                    try:
                        model.Add(
                            course_in_block[(base, b)]
                            == course_in_block[(other, b)]
                        )
                    except:
                        pass
       
        if x["type"] == "Consecutive":
            for i in range(len(x["courses"]) - 1):
                c1 = x["courses"][i]
                c2 = x["courses"][i + 1]

                if c1 not in courses or c2 not in courses:
                    continue

                for b in range(NUM_BLOCKS):
                    # c1 in block b => c2 must be in b-1 or b+1
                    allowed_blocks = []
                    if b - 1 >= 0:
                        allowed_blocks.append(course_in_block[(c2, b - 1)])
                    if b + 1 < NUM_BLOCKS:
                        allowed_blocks.append(course_in_block[(c2, b + 1)])

                    model.Add(
                        course_in_block[(c1, b)]
                        <= sum(allowed_blocks)
                    )

    # idk implimentation or smt
    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            for c in student.requestedCourses:
                if c in courses:
                    model.AddImplication(
                        timetables[(s, b, c)],
                        course_in_block[(c, b)]
                    )

    # objective
    model.Maximize(sum(timetables[(s, b, c)] for (s, b, c) in timetables))

    # solves
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("No feasible solution found.")

    # write solution back into YOUR Student objects
    for i, st in enumerate(students):
        st.assignedCourses = [None] * NUM_BLOCKS
        m = len(st.requestedCourses)
        if m == 0:
            continue

        for b in range(NUM_BLOCKS):
            chosen = None
            for c in st.requestedCourses:
                if solver.Value(timetables[(i, b, c)]) == 1:
                    chosen = c
                    break
            st.assignedCourses[b] = chosen
   
    # other stuff
    assignment = defaultdict(list)
    course_block_index_value = {}

    for c in courses:
        for b in range(NUM_BLOCKS):
            if solver.Value(course_in_block[(c, b)]) == 1:
                course_block_index_value[c] = b
                break

    for i, st in enumerate(students):

        for b in range(NUM_BLOCKS):
            chosen = None

            for c in st.requestedCourses:
                if solver.Value(timetables[(i, b, c)]) == 1:
                    chosen = c
                    break

            st.assignedCourses[b] = chosen

            if chosen is not None:
                assignment[chosen].append((st.id, b, i))

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

            # Filter out out-of-timetable courses (e.g., Peer Tutoring, Yearbook, Leadership)
            norm = normalize_text(f"{code} {description}")
            if any(k in norm for k in OUT_OF_TIMETABLE_KEYWORDS):
                continue

            # Some CSVs place the sections count in the last column (with leading commas).
            # Find the last non-empty cell and parse it as the sections count.
            sec = 0
            for cell in reversed(row):
                if (cell or "").strip():
                    sec = _to_int(cell)
                    break
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


def export_master_by_block_csv(
    sections: dict,
    courses: dict,
    section_rooms: dict,
    section_enrollments: dict,
    out_path: str,
):
    # Build list of labels per block
    blocks = {b: [] for b in range(NUM_BLOCKS)}
    for sec_id, info in sections.items():
        b = info.get("block", 0)
        code = info.get("course")
        name = courses[code].getName() if code in courses else code
        room = section_rooms.get(sec_id, "")
        enrolled = len(section_enrollments.get(sec_id, []))
        label = f"{name} ({sec_id})"
        if room:
            label = f"{label} @ {room}"
        label = f"{label} [{enrolled}]"
        blocks[b].append(label)

    # Write CSV with Block columns and rows containing sections
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = [f"Block {b+1}" for b in range(NUM_BLOCKS)]
        w.writerow(header)

        all_block_lists = [sorted(blocks[b]) for b in range(NUM_BLOCKS)]
        max_rows = max((len(lst) for lst in all_block_lists), default=0)
        for i in range(max_rows):
            row = [(all_block_lists[b][i] if i < len(all_block_lists[b]) else "") for b in range(NUM_BLOCKS)]
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


def print_students_with_full_requested(
    students: list,
    courses: dict,
    section_rooms: dict,
    count: int = 3,
    student_id=None,
):
    if not students:
        print("No students.")
        return

    if student_id is None:
        eligible = []
        for s in students:
            requested_hits = sum(
                1
                for c in s.assignedCourses
                if c is not None and c in s.requestedCourses
            )
            if requested_hits == NUM_BLOCKS:
                eligible.append(s)

        if not eligible:
            print("No student found with 8/8 requested courses.")
            return

        sample_count = min(count, len(eligible))
        selected = random.sample(eligible, sample_count)
    else:
        matches = [s for s in students if int(s.id) == int(student_id)]
        if not matches:
            print("Student not found:", student_id)
            return
        selected = [matches[0]]

    print("=== Full timetable for students with 8/8 requested ===")
    for st in selected:
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


def is_out_of_timetable(code: str, description: str) -> bool:
    norm = normalize_text(f"{code} {description}")
    return any(normalize_text(k) in norm for k in OUT_OF_TIMETABLE_KEYWORDS)


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

    # Determine active courses: those the solver decided to run (course_runs==1)
    active_codes = {code for code, entries in assignment.items() if entries}

    for code in sorted(active_codes):
        if code not in courses or code not in course_block_index:
            continue

        course = courses[code]
        cap = course.capacity if isinstance(course.capacity, int) and course.capacity > 0 else 30
        max_sections = course.section if isinstance(course.section, int) and course.section > 0 else 1

        enrolled_count = len(assignment.get(code, []))

        # Only open as many sections as needed to fit students above 50% fill
        # e.g. 45 students, cap=30 → need 2 sections (each gets ~22, above 15 min)
        # e.g. 12 students, cap=30 → need 1 section (12 >= 15? no, but 1 is minimum)
        min_fill = math.ceil(0.5 * cap)
        sections_needed = max(1, math.ceil(enrolled_count / cap))

        # Never exceed the course's allowed max sections
        sections_needed = min(sections_needed, max_sections)

        for idx in range(1, sections_needed + 1):
            sec_name = f"S{idx}"
            sec_id = f"{code}-{sec_name}"
            sections[sec_id] = {
                "course": code,
                "section": sec_name,
                "capacity": cap,
                "block": course_block_index[code],
                "department": course.department,
            }

    # Assign students to sections, ensuring each section meets the 50% minimum when possible.
    for code, entries in assignment.items():
        sec_ids = sorted([sid for sid, info in sections.items() if info["course"] == code])
        if not sec_ids:
            continue

        cap = sections[sec_ids[0]]["capacity"] if sec_ids else 0
        min_fill = int(math.ceil(0.5 * cap)) if cap > 0 else 0

        # Fill each section to the minimum first, then balance the remainder.
        total_min = min_fill * len(sec_ids)
        for i, (student_id, block, student_idx) in enumerate(entries):
            if i < total_min:
                sec_id = sec_ids[i % len(sec_ids)]
            else:
                sec_id = sec_ids[(i - total_min) % len(sec_ids)]
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
