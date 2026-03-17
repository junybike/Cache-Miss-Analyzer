#include <iostream>
#include <vector>

using namespace std;

typedef struct node
{
    int data;
    struct node *next;
} node_t;

int main()
{
    const int N = 10000000;
    vector<int> data(N);

    for (int i = 0; i < N; i++)
    {
        data[i] = i;
    }

    long sum = 0;
    for (int i = 0; i < N; i++)
    {
        sum += data[i];
    }

    cout << "sum: " << sum << endl;
    return 0;
}