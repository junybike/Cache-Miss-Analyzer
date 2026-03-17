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
    vector<int> v_int(N);

    for (int i = 0; i < N; i++)
    {
        v_int[i] = i;
    }

    long sum = 0;
    for (int i = 0; i < N; i++)
    {
        sum += v_int[i];
    }

    cout << "sum: " << sum << endl;

    int a_int[1000];
    for (int i = 0; i < 1000; i++)
    {
        a_int[i] = i;
    }

    node* n1 = new node();
    node* n2 = new node();
    node* n3 = new node();
    node* n4 = new node();
    node* n5 = new node();

    n1->next = n2;
    n2->next = n3;
    n3->next = n4;
    n4->next = n5;

    node* tmp = n1;

    while (tmp)
    {
        tmp->data = 0;
        tmp = tmp->next;
    }

    return 0;
}