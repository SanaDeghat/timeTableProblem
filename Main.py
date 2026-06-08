import csv
import math
import random
import re
from collections import Counter, defaultdict
import pickle

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

with open("course_code_names_dict.pkl", "rb") as f:
    course_code_names = pickle.load(f)



def main():
    courses = load_courses("DataFiles/Course Number of Sections.csv")
    students = load_students("DataFiles/cleanedstudentrequests.csv")
    blocking_rules = load_blocking_rules("DataFiles/course Simultaneous Blocking.csv")
    rooms = load_rooms("DataFiles/Staff list with rooms.csv")


    status, obj, course_block_index, assignment = solve(
        students,
        courses,
        blocking_rules
    )


    # loads variables onto a file
    with open("solution.pkl", "wb") as f:
        pickle.dump(
            (
                status,
                obj,
                course_block_index,
                assignment
            ),
            f
        )

    # gets preloaded variables from a file
    with open("solution.pkl", "rb") as f:
        status, obj, course_block_index, assignment = pickle.load(f)

    create_classes_and_students_file(assignment, blocking_rules, students)

    # (
    #     sections,
    #     section_enrollments,
    #     section_rooms,
    #     room_conflicts,
    #     invalid_room_assignments,
    #     overfilled_sections,
    #     underfilled_sections,
    # ) = assign_sections_and_rooms(students, courses, course_block_index, rooms, assignment, blocking_rules)

    # # Export student-level timetables to a distinct file.
    # export_master_csv(students, courses, section_rooms, "every_students_timetable.csv")
    # print("Exported every_students_timetable.csv\n")

    # # Export course-by-block master timetable (sections + rooms) to master_timetable.csv
    # export_master_by_block_csv(
    #     sections,
    #     courses,
    #     section_rooms,
    #     section_enrollments,
    #     "master_timetable.csv",
    # )

    # metrics(
    #     students,
    #     courses,
    #     blocking_rules,
    #     course_block_index,
    #     sections,
    #     section_enrollments,
    #     section_rooms,
    #     room_conflicts,
    #     invalid_room_assignments,
    #     overfilled_sections,
    #     underfilled_sections,
    #     obj,
    # )

    # print_students_with_full_requested(students, courses, section_rooms, count=3)

    # print(section_rooms)


def solve(
    students: list,
    courses: dict,
    blocking_rules: list
):
    model = cp_model.CpModel()

    timetables = {}
    course_in_block = {}

    # creates variables
    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            for c in student.requestedCourses:
                if c not in courses:
                    continue

                for sec in range(courses[c].section):
                    timetables[(s, b, c, sec)] = model.NewBoolVar(
                        f"s{s}_b{b}_c{c}_sec{sec}"
                    )

    for c, c_obj in courses.items():
        for sec in range(c_obj.section):
            for b in range(NUM_BLOCKS):
                course_in_block[(c, sec, b)] = model.NewBoolVar(
                    f"course_{c}_sec{sec}_b{b}"
                )


    # constraint 1: student dosent have more than 1 course per block
    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            model.AddAtMostOne(
                timetables[(s, b, c, sec)]
                for c in student.requestedCourses
                if c in courses
                for sec in range(courses[c].section)
                if (s, b, c, sec) in timetables
            )

    # constraint 2: course cant appear more than once
    for s, student in enumerate(students):
        for c in student.requestedCourses:
            if c not in courses:
                continue

            model.AddAtMostOne(
                timetables[(s, b, c, sec)]
                for b in range(NUM_BLOCKS)
                for sec in range(courses[c].section)
                if (s, b, c, sec) in timetables
            )
   
    # constraint 3: limit number of sections per course
    for c, course_obj in courses.items():
        max_sections = course_obj.section

        model.Add(
            sum(
                course_in_block[(c, sec, b)]
                for sec in range(max_sections)
                for b in range(NUM_BLOCKS)
            )
            <= max_sections
        )

    # each course must run at least once
    for c, c_obj in courses.items():
        model.Add(
            sum(
                course_in_block[(c, sec, b)]
                for sec in range(c_obj.section)
                for b in range(NUM_BLOCKS)
                if c_obj.section != 0
            ) >= 1
        )

    for c, course_obj in courses.items():
        cap = courses[c].capacity
        min_fill = cap // 2

        for sec in range(course_obj.section):
            for b in range(NUM_BLOCKS):

                enrolled = sum(
                    timetables[(s, b, c, sec)]
                    for s, student in enumerate(students)
                    if c in student.requestedCourses
                    if (s, b, c, sec) in timetables
                )

                # constraint 4: upper bound (capacity)
                model.Add(
                    enrolled <= cap * course_in_block[(c, sec, b)]
                )


    # constraint 5: course sequencing
    course_seq = load_course_sequencing()
    for before, after_list in course_seq.items():

        if before not in courses:
            continue

        for after in after_list:

            if after not in courses:
                continue

            for s, student in enumerate(students):

                if before not in student.requestedCourses:
                    continue

                if after not in student.requestedCourses:
                    continue

                # BEFORE course can only be in semester 1
                for b in range(4, 8):
                    for sec in range(courses[before].section):
                        if (s, b, before, sec) in timetables:
                            model.Add(
                                timetables[(s, b, before, sec)] == 0
                            )

                # AFTER course can only be in semester 2
                for b in range(0, 4):
                    for sec in range(courses[after].section):
                        if (s, b, after, sec) in timetables:
                            model.Add(
                                timetables[(s, b, after, sec)] == 0
                            )



    # constraint 6: follows blocking rules
    for rule in blocking_rules:

        if rule["type"] == "Simultaneous":
            courses_list = [c for c in rule["courses"] if c in courses]

            if len(courses_list) < 2:
                continue

            for b in range(NUM_BLOCKS):
                base = courses_list[0]

                base_in_block = sum(
                    course_in_block[(base, sec, b)]
                    for sec in range(courses[base].section)
                )

                for other in courses_list[1:]:
                    other_in_block = sum(
                        course_in_block[(other, sec, b)]
                        for sec in range(courses[other].section)
                    )

                    model.Add(base_in_block == other_in_block)
       
        elif rule["type"] == "Consecutive":
            courses_list = [c for c in rule["courses"] if c in courses]

            for i in range(len(courses_list) - 1):
                c1 = courses_list[i]
                c2 = courses_list[i + 1]

                for b in range(NUM_BLOCKS):

                    c1_in_b = sum(
                        course_in_block[(c1, sec, b)]
                        for sec in range(courses[c1].section)
                    )

                    c2_adjacent = []
                    if b - 1 >= 0:
                        c2_adjacent.append(
                            sum(
                                course_in_block[(c2, sec, b - 1)]
                                for sec in range(courses[c2].section)
                            )
                        )
                    if b + 1 < NUM_BLOCKS:
                        c2_adjacent.append(
                            sum(
                                course_in_block[(c2, sec, b + 1)]
                                for sec in range(courses[c2].section)
                            )
                        )

                    model.Add(
                        c1_in_b <= sum(c2_adjacent)
                    )

    # idk implimentation or smt
    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            for c in student.requestedCourses:
                if c not in courses:
                    continue

                # if student takes course c in block b,
                # they must be assigned to exactly one section of c in that block
                model.Add(
                    sum(
                        timetables[(s, b, c, sec)]
                        for sec in range(courses[c].section)
                    ) <= 1
                )

                for sec in range(courses[c].section):
                    model.AddImplication(
                        timetables[(s, b, c, sec)],
                        course_in_block[(c, sec, b)]
                    )


    open_sections = sum(
        course_in_block[(c, sec, b)]
        for c, course_obj in courses.items()
        for sec in range(course_obj.section)
        for b in range(NUM_BLOCKS)
    )

    model.Maximize(
        sum(timetables.values()) - open_sections
    )

    # solves
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 120
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("No feasible solution found.")

    # write solution back into YOUR Student objects
    for i, st in enumerate(students):
        st.assignedCourses = [None] * NUM_BLOCKS
        st.assignedSections = [None] * NUM_BLOCKS

        for b in range(NUM_BLOCKS):
            chosen_course = None
            chosen_section = None

            for c in st.requestedCourses:
                if c not in courses:
                    continue

                for sec in range(courses[c].section):
                    if solver.Value(timetables[(i, b, c, sec)]) == 1:
                        chosen_course = c
                        chosen_section = sec
                        break

                if chosen_course is not None:
                    break

            st.assignedCourses[b] = chosen_course
            st.assignedSections[b] = chosen_section
   
    # other stuff
    assignment = defaultdict(list)
    course_block_index_value = defaultdict(list)

    for c, c_obj in courses.items():
        for b in range(NUM_BLOCKS):
            for sec in range(c_obj.section):
                if solver.Value(course_in_block[(c, sec, b)]) == 1:
                    course_block_index_value[c].append((b, sec))

    for i, st in enumerate(students):

        st.assignedCourses = [None] * NUM_BLOCKS
        st.assignedSections = [None] * NUM_BLOCKS

        for b in range(NUM_BLOCKS):
            chosen_course = None
            chosen_section = None

            for c in st.requestedCourses:
                if c not in courses:
                    continue

                for sec in range(courses[c].section):
                    if solver.Value(timetables[(i, b, c, sec)]) == 1:
                        chosen_course = c
                        chosen_section = sec
                        break

                if chosen_course is not None:
                    break

            st.assignedCourses[b] = chosen_course
            st.assignedSections[b] = chosen_section

            # store full assignment (course + section + block)
            if chosen_course is not None:
                assignment[(chosen_course, chosen_section, b)].append(
                    (st.id, i)
                )

    return status, solver.ObjectiveValue(), course_block_index_value, assignment


def create_classes_and_students_file(assignments, blocking_rules, students):

    # print(blocking_rules)

    # block, course, section, num people
    section_enrollments = defaultdict(list)

    for course in assignments:
        section_enrollments[course] = len(assignments[course])

    # for course in section_enrollments:
    #     print(course, ":", course_code_names[course[0]])

    # block -> list of strings
    blocks = defaultdict(list)
    blocks2 = defaultdict(list)

    for (course, sec, block), count in section_enrollments.items():
        label = f"{course_code_names[course]}:({count})"
        blocks[block].append(label)
        blocks2[block].append((course, count))

    # ensure deterministic ordering
    for b in blocks:
        blocks[b].sort()


    for b in blocks2:
        new_block = []
        used = set()

        for rule in blocking_rules:
            if rule["type"] != "Simultaneous":
                continue

            group = set(rule["courses"])

            total = 0
            found = []

            for course, count in blocks2[b]:
                if course in group:
                    total += count
                    found.append(course)

            if found and total <= 30:
                new_block.append((tuple(found), total))
                used.update(found)

        for course, count in blocks2[b]:
            if course not in used:
                new_block.append((course, count))

        blocks2[b] = new_block

    for b in blocks2:
        print("Block:", b, "---------------------------------")
        for x in range(len(blocks2[b])):
            if isinstance(blocks2[b][x][0], tuple):
                courses_tuple, count = blocks2[b][x]

                course_names = " & ".join(
                    course_code_names[c]
                    for c in courses_tuple
                )

                blocks2[b][x] = (course_names, count)

            else:
                course_code, count = blocks2[b][x]

                blocks2[b][x] = (
                    course_code_names[course_code],
                    count
                )

            print(blocks2[b][x][0], ":", blocks2[b][x][1])


    # writes to file----------------------------------------------
    max_block = max(blocks2.keys(), default=-1) + 1
    max_rows = max((len(blocks2[b]) for b in range(max_block)), default=0)

    with open("master_timetable2.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # header
        writer.writerow([f"Block {b+1}" for b in range(max_block)])

        # rows
        for i in range(max_rows):
            row = []
            for b in range(max_block):
                if i < len(blocks2[b]):
                    row.append(blocks2[b][i])
                else:
                    row.append("")
            writer.writerow(row)
    # -----------------------------------------------------------------

    course_seq = load_course_sequencing()
    print(course_seq)

def load_course_sequencing():
    rules = defaultdict(list)

    with open("DataFiles/Course Sequencing.csv", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)

        for row in reader:
            if not row:
                continue

            # join row in case of weird CSV splitting
            text = ",".join(row)

            # remove keyword
            text = text.replace("Sequence", "").strip()

            # remove surrounding quotes
            text = text.replace('"', '')

            # extract pattern: A before B
            # also handles commas inside row
            matches = re.findall(r"([A-Z0-9\-]+)\s+before\s+([A-Z0-9\-]+)", text)

            for a, b in matches:
                rules[a].append(b)

    return dict(rules)


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

    # courseNames = defaultdict(list)

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

        # courseNames[code] = description

    # with open("course_code_names_dict.pkl", "wb") as f:
    #     pickle.dump(courseNames, f)

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


if __name__ == "__main__":
    main()
