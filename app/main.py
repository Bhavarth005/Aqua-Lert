from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base

# Create all tables (only for testing — later use migrations)
Base.metadata.create_all(bind=engine)

app = FastAPI()

# Dependency: get DB session for each request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def read_root():
    return {"message": "FastAPI + MySQL running!"}

@app.get("/db-check")
def db_check(db: Session = Depends(get_db)):
    result = db.execute("SELECT 1").fetchone()
    return {"db_status": result[0]}
