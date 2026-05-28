import csv
import random
from ortools.sat.python import cp_model

from Student import Student
from Class import Class


NUM_BLOCKS = 8

def main():
    courses = load_courses()
    students = load_students("DataFiles/cleanedstudentrequests.csv")

    print_data_structures(courses, students)

    status, obj = solve(students, courses, time_limit_s=15.0)
    # convert assigned course codes to Class objects (use course name for display)
    for st in students:
        for i, code in enumerate(st.assignedCourses):
            if code is None:
                continue
            if isinstance(code, str) and code in courses:
                st.assignedCourses[i] = courses[code]
    print("Solve status:", status)
    print()

    print_master_preview(students, limit=25)
    export_master_csv(students, "master_timetable.csv")
    print("Exported master_timetable.csv\n")

    print_courses_by_block(students)

    metrics(students, obj)


    print_one_student(students, student_id=None)
    print()

    export_student_counts_by_block(students, "student_counts_by_block.csv")
    print("Exported student_counts_by_block.csv")



def solve(students: list, courses : dict, time_limit_s: float = 5.0):
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
            course_in_block[(c, b)] = model.new_bool_var(f"course_{c}_block_{b}")


    # constraint 1: student dosent have more than 1 course per block
    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            model.AddAtMostOne(timetables[(s, b, c)] for c in student.requestedCourses)

    # constraint 2: course cant appear more than once
    for s, student in enumerate(students):
        for c in student.requestedCourses:
            model.AddAtMostOne(timetables[(s, b, c)] for b in range(NUM_BLOCKS))

    for s, student in enumerate(students):
        for b in range(NUM_BLOCKS):
            for c in student.requestedCourses:
                if c in courses:
                    model.AddImplication(
                        timetables[(s, b, c)],
                        course_in_block[(c, b)]
                    )
   
    # limit number of sections per course
    for c, course_obj in courses.items():
        max_sections = course_obj.section

        model.Add(
            sum(course_in_block[(c, b)] for b in range(NUM_BLOCKS)) <= max_sections
        )

    # no more than the max # of students per block
    for c in courses:
        for b in range(NUM_BLOCKS):
            model.Add(
                sum(timetables[(s, b, c)]
                    for s, student in enumerate(students)
                    if c in student.requestedCourses) <= courses[c].capacity
            )

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

    return status, solver.ObjectiveValue()


def export_student_counts_by_block(students: list, out_path: str):
    # counts[block][course] = number of students in that course during that block
    counts = {}

    for b in range(NUM_BLOCKS):
        counts[b] = {}

    # count students in each course in each block
    for st in students:
        for b, course in enumerate(st.assignedCourses):
            if course is None:
                continue

            # if course is a Class object, use its name/code nicely
            if hasattr(course, "getName"):
                course_name = course.getName()
            else:
                course_name = str(course)

            if course_name not in counts[b]:
                counts[b][course_name] = 0

            counts[b][course_name] += 1

    # collect all course names that appear anywhere
    all_courses = set()
    for b in range(NUM_BLOCKS):
        all_courses.update(counts[b].keys())

    all_courses = sorted(all_courses)

    # write CSV
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        header = ["Course"] + [f"Block {b + 1}" for b in range(NUM_BLOCKS)]
        writer.writerow(header)

        for course in all_courses:
            row = [course]

            for b in range(NUM_BLOCKS):
                row.append(counts[b].get(course, 0))

            writer.writerow(row)

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


def load_students(student_csv_path: str):
    students = []
    with open(student_csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        current_student_id = None
        current_grade = None
        current_courses = []
        
        for row in reader:
            if not row or len(row) < 2:
                continue
            
            # Check if this is a student ID row
            if row[0] == "ID":
                # Save previous student if exists
                if current_student_id is not None:
                    students.append(Student(current_student_id, current_grade, current_courses))
                    current_courses = []
                
                # Parse new student
                current_student_id = row[1].strip() if len(row) > 1 else None
                current_grade = row[3].strip() if len(row) > 3 else None
            
            # Skip header and empty rows
            elif row[0] == "Course" or not row[0].strip():
                continue
            
            # This is a course row
            elif current_student_id is not None and row[0].strip():
                course_code = row[0].strip()
                # Only add if it looks like a course code (contains dash)
                if "-" in course_code and course_code.upper() != "COURSE":
                    current_courses.append(course_code)
        
        # Don't forget the last student
        if current_student_id is not None:
            students.append(Student(current_student_id, current_grade, current_courses))
    
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