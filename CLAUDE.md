# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GitHub PR Explorer is a lightweight web application for browsing, filtering, and exploring GitHub Pull Requests. It uses the GitHub CLI (`gh`) for authentication and data fetching, with a Flask backend and Vue.js 3 frontend.

## Commands

### Run the Application
```bash
python app.py
```
The server runs on `http://127.0.0.1:5050` by default (configurable in `config.json`).

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Prerequisites
- GitHub CLI (`gh`) must be installed and authenticated via `gh auth login`
- Python 3.x with Flask

## Design Document 
Please read @docs/DESIGN.md to get acquainted with the design, this file will stay maintained after every change. Make sure to update this document whenever any design aspect changes 

