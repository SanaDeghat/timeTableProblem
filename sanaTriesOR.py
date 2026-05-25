import csv
import random
from ortools.sat.python import cp_model

from Student import Student
from Class import Class


NUM_BLOCKS = 8


import csv

def load_courses():
    course_csv_path="DataFiles/Course Tally.csv"
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
            print(row[3].strip())
            description = (row[2] or "").strip() if len(row) > 2 else ""
            department = (row[3] or "guess whos lowing their mind").strip() if len(row) > 3 else "hahahahaha"
            if not code or "-" not in code or code.lower() == "number":
                continue
            if code not in courses:
                courses[code] = Class(
                    code=code,
                    name=description,
                    department=department,     # this should be the department column, not the description
                    requestedPrimary= _to_int_sections(row[4] if len(row) > 6 else "98"),
                    requestedAlt=_to_int_sections(row[5])- _to_int_sections(row[4]),
                    capacity=_to_int_sections(row[6]),
                    section=_to_int_sections(row[7])
                )
                courses[code].print()
                print(code)

    


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
        print("Timetable sample:", {students[50].id: timetable[students[50].id]})
    print()


def solve(students: list, time_limit_s: float = 15.0):
    
    model = cp_model.CpModel()

    x = {}    
    take = {}  \

    for i, st in enumerate(students):
        m = len(st.requestedCourses)
        if m == 0:
            continue

        for b in range(NUM_BLOCKS):
            take[(i, b)] = model.NewBoolVar(f"take_s{i}_b{b}")
            for k in range(m):
                x[(i, b, k)] = model.NewBoolVar(f"x_s{i}_b{b}_k{k}")

            # 0 or 1 course in each block
            model.Add(sum(x[(i, b, k)] for k in range(m)) == take[(i, b)])

        # don't use the same requested entry twice
        for k in range(m):
            model.AddAtMostOne(x[(i, b, k)] for b in range(NUM_BLOCKS))

    BIG = 1000
    objective_terms = []
    for (i, b), t in take.items():
        objective_terms.append(-BIG * t)
    for (i, b, k), var in x.items():
        objective_terms.append(k * var)

    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.Solve(model)

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
            for k in range(m):
                if solver.Value(x[(i, b, k)]) == 1:
                    chosen = st.requestedCourses[k]
                    break
            st.assignedCourses[b] = chosen

    return status, solver.ObjectiveValue()


def export_master_csv(students: list, out_path: str):
    header = ["StudentID", "YOG"] + [f"Block{b+1}" for b in range(NUM_BLOCKS)]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for st in students:
            row = [st.id, st.yog] + [(c if c is not None else "NULL") for c in st.assignedCourses]
            w.writerow(row)


def print_master_preview(students: list, limit: int = 25):
    print("=== Master Timetable (preview) ===")
    print("StudentID | YOG | " + " | ".join([f"B{b+1}" for b in range(NUM_BLOCKS)]))
    for st in students[:limit]:
        blocks = " | ".join([(c if c is not None else "NULL") for c in st.assignedCourses])
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
        print(f"  Block {b+1}: {st.assignedCourses[b] if st.assignedCourses[b] is not None else 'NULL'}")
    print()


def main():
    courses = load_courses()
    students = load_students("DataFiles/Course Selection by student.csv")

    print_data_structures(courses, students)

    status, obj = solve(students, time_limit_s=15.0)
    print("Solve status:", status)
    print()

    print_master_preview(students, limit=25)
    export_master_csv(students, "master_timetable.csv")
    print("Exported master_timetable.csv\n")

    metrics(students, obj)

    print_one_student(students, student_id=None)


if __name__ == "__main__":
    load_courses()