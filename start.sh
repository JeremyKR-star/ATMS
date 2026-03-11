#!/bin/bash
echo "============================================"
echo "  ATMS - Advanced Training Management System"
echo "============================================"
echo ""

# Initialize database and seed data
python3 seed.py

echo ""
echo "Starting server..."
echo "Open http://localhost:8080 in your browser"
echo "Press Ctrl+C to stop"
echo ""
python3 server.py
