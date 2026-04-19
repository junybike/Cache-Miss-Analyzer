// Pointer chasing: scattered heap nodes cause a cache miss on every ->next.

#include <iostream>
#include <cstdlib>

struct Node
{
        int value;
        Node *next;
};

Node* build_list(int n)
{
        Node *head = nullptr;
        for (int i = 0; i < n; i++)
        {
                // Intentionally leaked to prevent allocator reuse and scatter nodes
                volatile char *pad = new char[4096];
                (void)pad;

                Node *node = new Node();
                node->value = i;
                node->next = head;
                head = node;
        }
        return head;
}

int main()
{
        const int N = 2000000;

        Node *head = build_list(N);

        long sum = 0;
        Node *curr = head;
        while (curr)
        {
                sum += curr->value;
                curr = curr->next;
        }

        std::cout << "sum: " << sum << std::endl;

        return 0;
}
