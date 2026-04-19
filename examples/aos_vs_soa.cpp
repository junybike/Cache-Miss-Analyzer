// AoS waste: hot loop reads only x and y from a 92-byte struct.

#include <iostream>
#include <vector>
#include <cmath>

struct Particle
{
        float x;
        float y;
        float z;
        char  name[64];
        float vx;
        float vy;
        float vz;
        int   id;
};

int main()
{
        const int N = 5000000;
        std::vector<Particle> particles(N);

        for (int i = 0; i < N; i++)
        {
                particles[i].x  = static_cast<float>(i) * 0.1f;
                particles[i].y  = static_cast<float>(i) * 0.2f;
                particles[i].z  = 0.0f;
                particles[i].vx = 1.0f;
                particles[i].vy = 1.0f;
                particles[i].vz = 0.0f;
                particles[i].id = i;
        }

        // Hot loop — only needs x and y but loads full 92-byte structs
        double total_dist = 0.0;
        for (int pass = 0; pass < 10; pass++)
        {
                for (int i = 0; i < N; i++)
                {
                        float dx = particles[i].x;
                        float dy = particles[i].y;
                        total_dist += std::sqrt(dx * dx + dy * dy);
                }
        }

        std::cout << "total distance: " << total_dist << std::endl;

        return 0;
}
