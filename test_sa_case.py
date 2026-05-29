from sqlalchemy import select, func, Column, Integer, String, case
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class EmailLog(Base):
    __tablename__ = 'emaillogs'
    id = Column(Integer, primary_key=True)
    status = Column(String)
    open_count = Column(Integer)

try:
    stmt1 = select(func.sum(func.case((EmailLog.open_count > 0, 1), else_=0)))
    print("func.case:")
    print(stmt1.compile(compile_kwargs={"literal_binds": True}))
except Exception as e:
    print("func.case exception:", type(e), e)

try:
    stmt2 = select(func.sum(case((EmailLog.open_count > 0, 1), else_=0)))
    print("case:")
    print(stmt2.compile(compile_kwargs={"literal_binds": True}))
except Exception as e:
    print("case exception:", type(e), e)
