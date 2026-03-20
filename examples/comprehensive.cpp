// comprehensive.cpp — A simplified game loop that exhibits six common
// cache-unfriendly patterns: pointer chasing, column-major strided access,
// AoS waste, hot/cold struct pollution, interleaved hot/cold fields,
// and random (indirect) access via a shuffled index array.
//
// Compile: g++ -g -no-pie comprehensive.cpp -o comprehensive
// Profile: ./profiler/run_perf.sh examples/comprehensive.cpp examples/comprehensive

#include <iostream>
#include <vector>
#include <cmath>
#include <cstdlib>
#include <algorithm>
#include <numeric>
#include <random>

// ---- Pointer chasing (linked-list pathfinding) ----
// Nodes are scattered across the heap, so following ->next causes
// a cache miss on virtually every step.

struct Waypoint
{
    float x;
    float y;
    float cost;
    Waypoint *next;
};

Waypoint *build_path(int n)
{
    Waypoint *head = nullptr;
    for (int i = 0; i < n; i++)
    {
        // Push allocations far apart to defeat allocator locality
        volatile char *spacer = new char[4096];
        (void)spacer;

        Waypoint *wp = new Waypoint();
        wp->x    = static_cast<float>(i) * 0.3f;
        wp->y    = static_cast<float>(i) * 0.7f;
        wp->cost = 1.0f;
        wp->next = head;
        head = wp;
    }
    return head;
}

// ---- Column-major traversal (terrain heightmap) ----
// Row-major 2D array traversed column-first. Each heightmap[r][c]
// skips an entire row, wasting the rest of the fetched cache line.

const int MAP_ROWS = 2048;
const int MAP_COLS = 2048;
int heightmap[MAP_ROWS][MAP_COLS];

// ---- AoS with many cold fields (projectile tracking) ----
// The collision loop only reads x and y, but each Projectile is 92
// bytes. Most of each cache line fetch is wasted on cold fields.

struct Projectile
{
    float x;
    float y;
    float z;
    char  owner[64];
    float vx;
    float vy;
    float vz;
    int   damage;
};

// ---- Large struct with hot/cold split (game entities) ----
// The physics update only touches position and velocity (16 bytes),
// but each Entity is 400+ bytes. Most of each cache line is wasted.
// Hot fields (x, y, vx, vy) are also separated by 128 bytes of
// cold rendering data, forcing loads from multiple cache lines.

struct Entity
{
    float x;             // hot — position
    float y;             // hot — position
    char  texture[128];  // cold — rendering
    float vx;            // hot — velocity (128 bytes away from x, y)
    float vy;            // hot — velocity
    char  ai_data[256];  // cold — AI state
    int   hp;            // cold
    int   id;            // cold
    double score;        // cold
};

int main()
{
    // === 1. Pointer chasing: walk a scattered linked list ===

    const int N_WAYPOINTS = 1500000;
    Waypoint *path = build_path(N_WAYPOINTS);

    float total_cost = 0.0f;
    Waypoint *curr = path;
    while (curr)
    {
        total_cost += curr->cost;
        curr = curr->next;
    }
    std::cout << "path cost: " << total_cost << std::endl;

    // === 2. Column-major traversal: stride across rows ===

    for (int r = 0; r < MAP_ROWS; r++)
        for (int c = 0; c < MAP_COLS; c++)
            heightmap[r][c] = (r * 7 + c * 13) % 256;

    long elevation_sum = 0;
    for (int c = 0; c < MAP_COLS; c++)        // outer = column
        for (int r = 0; r < MAP_ROWS; r++)    // inner = row (stride = COLS * 4)
            elevation_sum += heightmap[r][c];

    std::cout << "elevation sum: " << elevation_sum << std::endl;

    // === 3. AoS waste: hot loop reads two fields from a 92-byte struct ===

    const int N_PROJECTILES = 3000000;
    std::vector<Projectile> projectiles(N_PROJECTILES);

    for (int i = 0; i < N_PROJECTILES; i++)
    {
        projectiles[i].x      = static_cast<float>(i) * 0.1f;
        projectiles[i].y      = static_cast<float>(i) * 0.2f;
        projectiles[i].z      = 0.0f;
        projectiles[i].vx     = 1.0f;
        projectiles[i].vy     = 1.0f;
        projectiles[i].vz     = 0.0f;
        projectiles[i].damage = 10;
    }

    double total_dist = 0.0;
    for (int pass = 0; pass < 10; pass++)
    {
        for (int i = 0; i < N_PROJECTILES; i++)
        {
            float dx = projectiles[i].x;
            float dy = projectiles[i].y;
            total_dist += std::sqrt(dx * dx + dy * dy);
        }
    }
    std::cout << "total distance: " << total_dist << std::endl;

    // === 4. Hot/cold + struct reorder: 400-byte struct, 16 hot bytes ===

    const int N_ENTITIES = 1500000;
    std::vector<Entity> entities(N_ENTITIES);

    for (int i = 0; i < N_ENTITIES; i++)
    {
        entities[i].x     = static_cast<float>(i);
        entities[i].y     = static_cast<float>(i) * 0.5f;
        entities[i].vx    = 1.0f;
        entities[i].vy    = 0.5f;
        entities[i].hp    = 100;
        entities[i].id    = i;
        entities[i].score = 0.0;
    }

    for (int step = 0; step < 10; step++)
    {
        for (int i = 0; i < N_ENTITIES; i++)
        {
            entities[i].x += entities[i].vx;
            entities[i].y += entities[i].vy;
        }
    }
    std::cout << "entity[0] pos: " << entities[0].x
              << ", " << entities[0].y << std::endl;

    // === 5. Random / indirect access: shuffled index lookup ===

    const int N_LOOKUPS = 5000000;
    std::vector<int> scores(N_LOOKUPS);
    std::vector<int> ranking(N_LOOKUPS);

    for (int i = 0; i < N_LOOKUPS; i++)
        scores[i] = i;

    std::iota(ranking.begin(), ranking.end(), 0);
    std::mt19937 rng(42);
    std::shuffle(ranking.begin(), ranking.end(), rng);

    long score_total = 0;
    for (int i = 0; i < N_LOOKUPS; i++)
        score_total += scores[ranking[i]];

    std::cout << "score total: " << score_total << std::endl;

    return 0;
}
