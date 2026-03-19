// Random access via shuffled indices defeats hardware prefetching.

#include <iostream>
#include <vector>
#include <algorithm>
#include <numeric>
#include <random>

int main()
{
    const int N = 10000000;

    std::vector<int> data(N);
    std::vector<int> indices(N);

    for (int i = 0; i < N; i++)
        data[i] = i;

    std::iota(indices.begin(), indices.end(), 0);
    std::mt19937 rng(42);
    std::shuffle(indices.begin(), indices.end(), rng);

    long sum = 0;
    for (int i = 0; i < N; i++)
        sum += data[indices[i]];

    long sum_seq = 0;
    for (int i = 0; i < N; i++)
        sum_seq += data[i];

    std::cout << "random sum:     " << sum << std::endl;
    std::cout << "sequential sum: " << sum_seq << std::endl;

    return 0;
}
