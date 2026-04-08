#!/bin/bash
# ATMS Test Suite Runner Script

set -e

echo "=========================================="
echo "ATMS Test Suite Runner"
echo "=========================================="
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "ERROR: pytest not found. Installing test dependencies..."
    pip install -r requirements-test.txt
fi

# Parse command line arguments
TEST_PATH="tests"
COVERAGE=false
PARALLEL=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --coverage)
            COVERAGE=true
            shift
            ;;
        --parallel)
            PARALLEL=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --file)
            TEST_PATH="tests/$2"
            shift 2
            ;;
        --help)
            echo "Usage: ./run_tests.sh [options]"
            echo ""
            echo "Options:"
            echo "  --coverage    Generate coverage report"
            echo "  --parallel    Run tests in parallel"
            echo "  --verbose     Verbose output"
            echo "  --file FILE   Run specific test file"
            echo "  --help        Show this help"
            exit 0
            ;;
        *)
            TEST_PATH=$1
            shift
            ;;
    esac
done

# Build pytest command
PYTEST_CMD="pytest $TEST_PATH"

if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -vv"
fi

if [ "$COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=. --cov-report=html --cov-report=term-missing"
fi

if [ "$PARALLEL" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -n auto"
fi

echo "Running: $PYTEST_CMD"
echo ""

# Run tests
$PYTEST_CMD

# Print results
echo ""
echo "=========================================="
echo "Test run completed!"
echo "=========================================="

if [ "$COVERAGE" = true ]; then
    echo "Coverage report: htmlcov/index.html"
fi
