import csv

from Student import Student 
from Class import Class 

students = []
courses = []

def main(): 
    S = Student(1234)
    S.print()

# returns a 2D labeled table with rows and columns
def getFile(fileName):
    df = pd.read_csv(fileName + '.csv')
    return df

if __name__ == "__main__":
    main()

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