#!/bin/bash

python app.py 2>&1 | tee gh-pr-explorer.log
exit 0 
