"""
Quick manual test for the visualizer — run this directly to see the animation.
No AWS credentials or API key needed.
"""

from mini_claude.visualizer import open_visualization

# A simple example with interesting variable changes at each step
code = """\
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

numbers = [3, 4, 5]
results = []

for num in numbers:
    result = factorial(num)
    results.append(result)

print(results)
"""

path = open_visualization(code)
print(f"Opened: {path}")
