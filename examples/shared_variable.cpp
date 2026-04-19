#include <iostream>
#include <thread>
#include <vector>
#include <atomic>
#include <chrono>

// ─────────────────────────────────────────────────────────────────────────────
// Problem 1: FALSE SHARING
// Two threads write to different variables that happen to sit on the same
// 64-byte cache line. Every write by one core invalidates the other core's
// cached copy of the entire line, even though they touch different bytes.
// ─────────────────────────────────────────────────────────────────────────────

struct SharedCounters
{
        long counter_a = 0;   // used by thread A
        long counter_b = 0;   // used by thread B
        // Both fit in one 64-byte cache line → false sharing
};

SharedCounters counters;

void increment_a(int iterations)
{
        for (int i = 0; i < iterations; ++i)
                counters.counter_a++;
}

void increment_b(int iterations)
{
        for (int i = 0; i < iterations; ++i)
                counters.counter_b++;
}


// ─────────────────────────────────────────────────────────────────────────────
// Problem 2: TRUE SHARING — unprotected global counter
// Both threads read-modify-write the same variable with no synchronisation.
// Causes data races AND cache-line ping-pong between cores.
// ─────────────────────────────────────────────────────────────────────────────

long global_sum = 0;   // global, written by every thread

void partial_sum(const std::vector<int> &data, int start, int end)
{
        for (int i = start; i < end; ++i)
                global_sum += data[i];   // unsynchronised write to shared global
}


// ─────────────────────────────────────────────────────────────────────────────
// Problem 3: SHARED POINTER ARGUMENT
// A single result struct is passed by pointer to two threads. Both threads
// write into different fields, but the struct is small enough that both
// fields share a cache line.
// ─────────────────────────────────────────────────────────────────────────────

struct Result
{
        long part_a = 0;
        long part_b = 0;
};

void compute_a(Result *result, const std::vector<int> &data)
{
        long sum = 0;
        for (int i = 0; i < (int)data.size() / 2; ++i)
                sum += data[i];
        result->part_a = sum;   // write to shared struct — false sharing with part_b
}

void compute_b(Result *result, const std::vector<int> &data)
{
        long sum = 0;
        for (int i = (int)data.size() / 2; i < (int)data.size(); ++i)
                sum += data[i];
        result->part_b = sum;   // write to shared struct — false sharing with part_a
}


// ─────────────────────────────────────────────────────────────────────────────
// Problem 4: SHARED VECTOR via std::ref
// A single std::vector is passed by reference to multiple threads. Each
// thread writes to a different index range, but the vector's internal
// metadata (size, capacity, data pointer) is a single shared cache line
// that all threads read on every iteration.
// ─────────────────────────────────────────────────────────────────────────────

void fill_range(std::vector<int> &vec, int start, int end, int value)
{
        for (int i = start; i < end; ++i)
                vec[i] = value;   // shared vector metadata causes coherency traffic
}


// ─────────────────────────────────────────────────────────────────────────────
// main: launch all four patterns
// ─────────────────────────────────────────────────────────────────────────────

int main()
{
        const int N          = 10'000'000;
        const int HALF       = N / 2;

        std::vector<int> data(N, 1);

        // ── Problem 1: false sharing on struct fields ─────────────────────────────
        {
                std::thread t1(increment_a, N);
                std::thread t2(increment_b, N);
                t1.join();
                t2.join();
                std::cout << "False sharing counters: "
                                    << counters.counter_a << ", " << counters.counter_b << "\n";
        }

        // ── Problem 2: true sharing — unprotected global ──────────────────────────
        {
                std::thread t1(partial_sum, std::ref(data), 0,    HALF);
                std::thread t2(partial_sum, std::ref(data), HALF, N);
                t1.join();
                t2.join();
                std::cout << "Global sum (racy): " << global_sum << "\n";
        }

        // ── Problem 3: shared pointer to Result struct ────────────────────────────
        {
                Result result;
                std::thread t1(compute_a, &result, std::ref(data));
                std::thread t2(compute_b, &result, std::ref(data));
                t1.join();
                t2.join();
                std::cout << "Result: " << result.part_a + result.part_b << "\n";
        }

        // ── Problem 4: shared vector via std::ref ─────────────────────────────────
        {
                std::vector<int> output(N, 0);
                std::thread t1(fill_range, std::ref(output), 0,    HALF, 1);
                std::thread t2(fill_range, std::ref(output), HALF, N,    2);
                t1.join();
                t2.join();
                std::cout << "Output[0]=" << output[0]
                                    << " Output[N-1]=" << output[N - 1] << "\n";
        }

        return 0;
}
