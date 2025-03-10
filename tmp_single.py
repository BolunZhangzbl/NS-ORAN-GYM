# import posix_ipimport time# Create or open a named semaphorsemaphore_name = "/my_semaphore"# This creates the semaphore if it doesn't exist (initial value = 0)# O_CREAT: Creates the semaphore if it doesn't already exist# 0: Initial value of the semaphore (0 means the semaphore is locked at start)semaphore = posix_ipc.Semaphore(semaphore_name, posix_ipc.O_CREAT, initial_value=1)print("Task 1: Acquiring semaphore...")# Simulating task 1 that needs the semaphoresemaphore.acquire()print("Task 1: Semaphore acquired."# Task 1 does some work (simulated by sleep)time.sleep(2)print("Task 1: Releasing semaphore...")semaphore.release()print("Task 1: Semaphore release# Now Task 2 starts (this would normally wait for the semaphoreprint("Task 2: Waiting for semaphore..."semaphore.acquire()print("Task 2: Semaphore acquired.")# Task 2 does some work (simulated by sleep)time.sleep(2)print("Task 2: Releasing semaphore...")semaphore.release()print("Task 2: Semaphore released.")# Clean up: Unlink the semaphoresemaphore.unlink()print("Semaphore unlinked."

import posix_ipc
import time

# Semaphore name
semaphore_name = "/my_semaphore"

# Create or open a named semaphore with an initial value of 0 (locked)
semaphore = posix_ipc.Semaphore(semaphore_name, posix_ipc.O_CREAT, initial_value=0)

def task_1():
    print("Task 1: Acquiring semaphore...")
    semaphore.acquire()
    print("Task 1: Semaphore acquired.")
    
    # Simulating some work in task 1 (e.g., sleep)
    time.sleep(2)
    
    print("Task 1: Releasing semaphore...")
    semaphore.release()

def task_2():
    print("Task 2: Waiting for semaphore...")
    semaphore.acquire()
    print("Task 2: Semaphore acquired.")
    
    # Simulating some work in task 2 (e.g., sleep)
    time.sleep(2)
    
    print("Task 2: Releasing semaphore...")
    semaphore.release()

# Running tasks sequentially (in the correct order)
task_1()  # Task 1 will acquire, do work, and release the semaphore
task_2()  # Task 2 will acquire the semaphore after Task 1 releases it

# Clean up: Unlink the semaphore
semaphore.unlink()
print("Semaphore unlinked.")
