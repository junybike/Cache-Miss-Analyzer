// Hot/cold partitioning: 600+ byte User struct where the hot loop
// only touches id, score, and active (13 bytes).

#include <iostream>
#include <vector>
#include <cstring>

struct User
{
        int    id;
        double score;
        bool   active;

        // Cold — only read on profile view
        char   name[64];
        char   email[128];
        char   bio[256];
        char   preferences[128];
        int    login_count;
        double account_balance;
};

int main()
{
        const int N = 2000000;
        std::vector<User> users(N);

        for (int i = 0; i < N; i++)
        {
                users[i].id     = i;
                users[i].score  = static_cast<double>(i % 100) + 0.5;
                users[i].active = (i % 3 != 0);
                std::memset(users[i].name, 'a', sizeof(users[i].name) - 1);
                std::memset(users[i].email, 'b', sizeof(users[i].email) - 1);
                std::memset(users[i].bio, 'c', sizeof(users[i].bio) - 1);
                std::memset(users[i].preferences, 'd', sizeof(users[i].preferences) - 1);
                users[i].login_count     = i % 1000;
                users[i].account_balance = i * 1.01;
        }

        double total = 0.0;
        int    count = 0;
        for (int i = 0; i < N; i++)
        {
                if (users[i].active)
                {
                        total += users[i].score;
                        count++;
                }
        }

        double avg = (count > 0) ? total / count : 0.0;
        std::cout << "average score of active users: " << avg << std::endl;
        std::cout << "active users: " << count << std::endl;

        return 0;
}
