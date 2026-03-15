#!/bin/bash
kill -9 23858 2>/dev/null
sleep 1
lsof -ti :8080 && echo "still running" || echo "port 8080 clear"
lsof -ti :5000 && echo "5000 running" || echo "5000 not running"
