import csv
import random
import math
from ortools.sat.python import cp_model

from Student import Student
from Class import Class


NUM_BLOCKS = 8


def main():
    courses = load_courses()
    rooms_by_dept = load_rooms("DataFiles/Staff list with rooms.csv")
    students = load_students("DataFiles/Course Selection by student.csv")

    print_data_structures(courses, students)

    status, obj, scheduled_sections, room_assignments = solve(courses, students, rooms_by_dept, time_limit_s=15.0)
    # convert assigned course codes to Class objects (use course name for display)
    for st in students:
        for i, code in enumerate(st.assignedCourses):
            if code is None:
                continue
            if isinstance(code, str) and code in courses:
                st.assignedCourses[i] = courses[code]
    print("Solve status:", status)
    print()
    # print scheduled sections summary
    print("=== Scheduled Sections Summary ===")
    for c_code, blocks in scheduled_sections.items():
        total = sum(blocks.values())
        if total > 0:
            print(f"{c_code}: total sections={total}, by block={blocks}")
    print()
    # print a few room assignments
    print("=== Sample Room Assignments (first 20) ===")
    for r in room_assignments[:20]:
        print(r)
    print()

    print_master_preview(students, limit=25)
    export_master_csv(students, "master_timetable.csv")
    print("Exported master_timetable.csv\n")

    metrics(students, obj)


    print_one_student(students, student_id=None)


def solve(courses: dict, students: list, rooms_by_dept: dict, time_limit_s: float = 15.0):
    model = cp_model.CpModel()

    timetables = {}

    # creates student assignment variables (student s in block b taking course c)
    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            for c in student.requestedCourses:
                timetables[(s, b, c)] = model.NewBoolVar(f"table_s{s}_b{b}_c{c}")

    # section distribution variables: how many sections of course c run in block b
    sections_in_block = {}
    for c_code, cls in courses.items():
        for b in range(NUM_BLOCKS):
            sections_in_block[(c_code, b)] = model.NewIntVar(0, cls.section, f"secs_{c_code}_b{b}")

    # each course must run exactly the declared number of sections across all blocks
    for c_code, cls in courses.items():
        model.Add(sum(sections_in_block[(c_code, b)] for b in range(NUM_BLOCKS)) == cls.section)

    # rooms capacity per department: ensure we don't schedule more sections in a block than available rooms
    rooms_count_by_dept = {d: len(rlist) for d, rlist in rooms_by_dept.items()}
    for b in range(NUM_BLOCKS):
        for dept, rcnt in rooms_count_by_dept.items():
            if rcnt <= 0:
                # no available rooms info for this department; skip strict room-capacity constraint
                continue
            # sum of sections scheduled in block b for courses in this dept <= available rooms
            model.Add(
                sum(sections_in_block[(c_code, b)] for c_code, cls in courses.items() if cls.department == dept)
                <= rcnt
            )

    # constraint 1: student doesn't have more than 1 course per block
    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            model.AddAtMostOne(timetables[(s, b, c)] for c in student.requestedCourses)

    # constraint 2: a student cannot take the same course more than once across blocks
    for s, student in enumerate(students):
        for c in student.requestedCourses:
            model.AddAtMostOne(timetables[(s, b, c)] for b in range(NUM_BLOCKS))

    # capacity and minimum-fill constraints per course per block
    for c_code, cls in courses.items():
        cap = cls.capacity
        min_per_section = math.ceil(0.5 * cap)
        for b in range(NUM_BLOCKS):
            # total students assigned to course c in block b
            assigned_in_block = sum(timetables[(s, b, c_code)] for s in range(len(students)) if (s, b, c_code) in timetables)
            # cannot exceed total capacity provided by sections scheduled in this block
            model.Add(assigned_in_block <= cap * sections_in_block[(c_code, b)])
            # if sections are scheduled, enforce minimum fill per section (aggregate)
            model.Add(assigned_in_block >= min_per_section * sections_in_block[(c_code, b)])

    # enforce blocking rules: courses listed in the same simultaneous blocking must have identical section distributions across blocks
    blocking_groups = load_blocking_rules("DataFiles/Course Blocking Rules.csv")
    for group in blocking_groups:
        # only consider codes that exist in courses
        group_codes = [c for c in group if c in courses]
        if len(group_codes) < 2:
            continue
        first = group_codes[0]
        for other in group_codes[1:]:
            for b in range(NUM_BLOCKS):
                model.Add(sections_in_block[(first, b)] == sections_in_block[(other, b)])

    # objective: maximize number of assigned student-course slots
    model.Maximize(sum(timetables[(s, b, c)] for (s, b, c) in timetables))

    # solves
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # return gracefully with empty scheduling info
        return status, 0.0, {}, []

    # write solution back into Student objects (course codes per block)
    for i, st in enumerate(students):
        st.assignedCourses = [None] * NUM_BLOCKS
        for b in range(NUM_BLOCKS):
            chosen = None
            for c in st.requestedCourses:
                if solver.Value(timetables[(i, b, c)]) == 1:
                    chosen = c
                    break
            st.assignedCourses[b] = chosen

    # extract sections_in_block values and assign concrete room numbers greedily
    scheduled_sections = {}
    for c_code, cls in courses.items():
        scheduled_sections[c_code] = {}
        for b in range(NUM_BLOCKS):
            cnt = solver.Value(sections_in_block[(c_code, b)])
            scheduled_sections[c_code][b] = cnt

    # assign rooms per department per block
    room_assignments = []  # tuples (course_code, block, section_index, room)
    used_rooms = {b: set() for b in range(NUM_BLOCKS)}
    for c_code, blocks in scheduled_sections.items():
        dept = courses[c_code].department
        available_rooms = list(rooms_by_dept.get(dept, []))
        for b, cnt in blocks.items():
            for sec_idx in range(cnt):
                # pick first unused room for this block
                room = None
                for r in available_rooms:
                    if r not in used_rooms[b]:
                        room = r
                        used_rooms[b].add(r)
                        break
                if room is None:
                    room = f"UNASSIGNED-{dept}-{b}-{sec_idx}"
                room_assignments.append((c_code, b, sec_idx, room))

    # return status, objective, scheduled_sections, room assignments
    return status, solver.ObjectiveValue(), scheduled_sections, room_assignments


def load_courses():
    course_csv_path = "DataFiles/Course Tally.csv"
    courses = {}

    def _to_int_sections(value: str) -> int:
        value = (value or "").strip()
        if not value:
            return 0
        try:
            return int(float(value))
        except ValueError:
            return 0

    with open(course_csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            print("Raw row:", row)
            if not row or len(row) < 3:
                continue
            code = (row[1] or "").strip() if len(row) > 1 else ""
            if len(row) > 3:
                print(row[3].strip())
            description = (row[2] or "").strip() if len(row) > 2 else ""
            department = (row[3] or "guess whos lowing their mind").strip() if len(row) > 3 else "hahahahaha"
            if not code or "-" not in code or code.lower() == "number":
                continue
            if code not in courses:
                courses[code] = Class(
                    code=code,
                    name=description,
                    department=department,
                    requestedPrimary=_to_int_sections(row[4] if len(row) > 6 else "98"),
                    requestedAlt=_to_int_sections(row[5]) - _to_int_sections(row[4]) if len(row) > 5 else 0,
                    capacity=_to_int_sections(row[6]) if len(row) > 6 else 0,
                    section=_to_int_sections(row[7]) if len(row) > 7 else 0,
                )
                courses[code].print()
                print(code)
    return courses


def load_rooms(rooms_csv_path: str):
    rooms_by_dept = {}
    try:
        with open(rooms_csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dept = (row.get("Department") or "").strip()
                room = (row.get("Num") or "").strip()
                if not dept or not room:
                    continue
                rooms_by_dept.setdefault(dept, []).append(room)
    except FileNotFoundError:
        return {}
    return rooms_by_dept


def load_blocking_rules(blocking_csv_path: str):
    groups = []
    try:
        with open(blocking_csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 3:
                    continue
                key = (row[1] or "").strip()
                text = (row[2] or "").strip()
                if key != "Course - Blocking":
                    continue
                # expect text like: Schedule A, B, C in a Simultaneous blocking
                if "Schedule" in text:
                    try:
                        start = text.index("Schedule") + len("Schedule")
                        end = text.index(" in ") if " in " in text else len(text)
                        codes_part = text[start:end].strip()
                        codes = [c.strip().strip(' ,') for c in codes_part.split(",") if c.strip()]
                        if codes:
                            groups.append(codes)
                    except ValueError:
                        continue
    except FileNotFoundError:
        return []
    return groups


def load_students(student_csv_path: str):
    students = []
    with open(student_csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        course_cols = [c for c in (reader.fieldnames or []) if c and c.startswith("C")]
        course_cols.sort(key=lambda x: int(x[1:]))

        for row in reader:
            sid = row["ID"]
            yog = row["YOG"]

            requested = []
            for c in course_cols:
                val = (row.get(c) or "").strip()
                if val:
                    requested.append(val)

            students.append(Student(sid, yog, requested))

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

    timetable = {st.id: [None] * NUM_BLOCKS for st in students}
    print(f"Timetable structure: dict[int, list[Optional[str]]], size={len(timetable)}")
    if students:
        sample_idx = 50 if len(students) > 50 else 0
        print("Timetable sample:", {students[sample_idx].id: timetable[students[sample_idx].id]})
    print()


def export_master_csv(students: list, out_path: str):
    header = ["StudentID", "YOG"] + [f"Block{b+1}" for b in range(NUM_BLOCKS)]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for st in students:
            row = [st.id, st.yog] + [((c.getName() if hasattr(c, 'getName') else str(c)) if c is not None else "NULL") for c in st.assignedCourses]
            w.writerow(row)


def print_master_preview(students: list, limit: int = 25):
    print("=== Master Timetable (preview) ===")
    print("StudentID | YOG | " + " | ".join([f"B{b+1}" for b in range(NUM_BLOCKS)]))
    for st in students[:limit]:
        blocks = " | ".join([((c.getName() if hasattr(c, 'getName') else str(c)) if c is not None else "NULL") for c in st.assignedCourses])
        print(f"{st.id} | {st.yog} | {blocks}")
    if len(students) > limit:
        print(f"... ({len(students) - limit} more students not shown)")
    print()


def metrics(students: list, objective_value: float):
    total_requests = sum(len(st.requestedCourses) for st in students)
    placed = sum(1 for st in students for c in st.assignedCourses if c is not None)

    pct_requests_placed = (placed / total_requests * 100.0) if total_requests else 0.0

    full = sum(1 for st in students if sum(1 for c in st.assignedCourses if c is not None) == NUM_BLOCKS)
    pct_full = (full / len(students) * 100.0) if students else 0.0

    half = 0
    for st in students:
        req = len(st.requestedCourses)
        if req == 0:
            continue
        placed_st = sum(1 for c in st.assignedCourses if c is not None)
        if placed_st >= 0.5 * req:
            half += 1
    pct_half = (half / len(students) * 100.0) if students else 0.0

    print("=== Basic Metrics (Early Evaluation Only) ===")
    print("Optimization score:", objective_value)
    print("Total requested courses:", total_requests)
    print("Total placed blocks:", placed)
    print(f"% requests placed: {pct_requests_placed:.2f}%")
    print(f"% students with 8/8 blocks filled: {pct_full:.2f}%")
    print(f"% students with >=50% requests placed: {pct_half:.2f}%")
    print()


def print_one_student(students: list, student_id=None):
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
        display = (c.getName() if hasattr(c, 'getName') else str(c)) if c is not None else 'NULL'
        print(f"  Block {b+1}: {display}")
    print()


if __name__ == "__main__":
    main()