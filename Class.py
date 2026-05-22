class Class:

    def __init__(self, id, description="", sections=0):
        self.id = id               
        self.description = description
        self.sections = int(sections) if str(sections).isdigit() else 0

    def print(self):
        print(self.id, self.description, self.sections)

    def __repr__(self):
        return f"Class(id={self.id}, sections={self.sections})"