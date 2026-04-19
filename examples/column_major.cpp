// Column-major traversal of a row-major matrix: each access strides by
// an entire row, defeating spatial locality and hardware prefetching.

#include <iostream>

const int ROWS = 4096;
const int COLS = 4096;

int matrix[ROWS][COLS];

int main()
{
        for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                        matrix[r][c] = r + c;

        // Column-major: stride = COLS * sizeof(int) per access
        long sum_col = 0;
        for (int c = 0; c < COLS; c++)
                for (int r = 0; r < ROWS; r++)
                        sum_col += matrix[r][c];

        // Row-major: sequential, cache-friendly
        long sum_row = 0;
        for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                        sum_row += matrix[r][c];

        std::cout << "col-major sum: " << sum_col << std::endl;
        std::cout << "row-major sum: " << sum_row << std::endl;

        return 0;
}
