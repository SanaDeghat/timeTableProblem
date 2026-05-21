import csv

from Student import Student 
from Class import Class 

def main():

    # dict of all students in this format: {"id" : Student Obj}
    students = {}
    fileName = "Course Selection by student"

    # opens data file
    with open(f"DataFiles/{fileName}.csv", mode='r') as file:
        data = csv.reader(file)
        next(data, None)

        # loops through all the student data
        for stu in data:
            id = stu[0]

            students[id] = Student(id, stu[1])
        
    for s in students:
        students[s].print()

if __name__ == "__main__":
    main()
