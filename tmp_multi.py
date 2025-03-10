import posix_ipc
import time
from multiprocessing import Process

# Create or open a named semaphore
nameMetricsReadySemaphore = "/metrics_ready_semaphore"
semaphore = posix_ipc.Semaphore(nameMetricsReadySemaphore, posix_ipc.O_CREAT, initial_value=0)

def producer():
    print("Producer: Working...")
    time.sleep(5)  # Simulate work
    print("Producer: Releasing semaphore.")
    semaphore.release()

def consumer():
    print("Consumer: Waiting for semaphore...")
    semaphore.acquire()
    print("Consumer: Semaphore acquired. Processing data...")

# Start the producer and consumer processes
producer_process = Process(target=producer)
consumer_process = Process(target=consumer)

producer_process.start()
consumer_process.start()

producer_process.join()
consumer_process.join()

# Clean up the semaphore
semaphore.unlink()
