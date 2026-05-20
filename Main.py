import pandas as pd

from Student import Student 
from Class import Class 

S = Student(1234)
S.print()

# returns a 2D labeled table with rows and columns
def getFile(fileName):
    df = pd.read_csv(fileName + '.csv')

    return df