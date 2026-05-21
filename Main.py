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
    