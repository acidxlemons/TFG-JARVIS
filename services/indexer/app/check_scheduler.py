
import sys
from app.main import scheduler

print(f"Scheduler Running: {scheduler.running}")
print("Jobs:")
for job in scheduler.get_jobs():
    print(f"- ID: {job.id}, Next Run: {job.next_run_time}")
