# Talk2Excel --- Autonomous Build Instructions

Build Talk2Excel autonomously in this repository.

Work in an iterative build-test-fix loop until the application is
complete and all acceptance criteria pass.

First check access to the OpenAI API using the `OPENAI_API_KEY`
environment variable. If access is unavailable, stop the process and
notify the developer.

------------------------------------------------------------------------

# Talk2Excel --- High-Level Requirements

## Product Overview

Talk2Excel is a lightweight local application that allows users to
interact with Excel data using natural language. Instead of writing
formulas or pivot tables, users can upload a spreadsheet and ask
questions in a chat interface to explore and analyze the data.

The system uses a large language model to interpret questions, generate
data analysis, and return results as explanations, tables, or charts.

------------------------------------------------------------------------

# Core Capabilities

## 1. Conversational Data Analysis

The application provides a chat-style interface that allows users to ask
questions about their Excel data in natural language.

### Example Queries

-   "List the top 10 customers by total sales"
-   "Show total profit in the West region"
-   "Show total sales by sub-category in the Technology category"

The system interprets the question and returns results in a clear,
structured format.

------------------------------------------------------------------------

## 2. Local Execution

The application runs entirely on a user's local computer.

### Benefits

-   No data upload to external services
-   Suitable for sensitive or internal datasets
-   Easy to deploy for experimentation and internal use

------------------------------------------------------------------------

## 3. Secure AI Connectivity

Users can configure the application by entering their OpenAI API key.

The key is:

-   stored securely for future sessions in persistent storage
-   never exposed in logs or user interface
-   used to connect to the AI model for analysis requests

The default AI model used for analysis is **GPT-5.4**.

------------------------------------------------------------------------

## 4. Excel Data Ingestion

Users can upload an Excel file for analysis.

After upload, the application:

-   loads the dataset
-   prepares it for conversational queries
-   allows the user to inspect the structure of the data

------------------------------------------------------------------------

## 5. Data Schema Transparency

To help users understand and validate the dataset, the application
provides a schema view showing:

-   column names
-   data types
-   basic dataset structure

This helps ensure the AI is interpreting the data correctly.

------------------------------------------------------------------------

## 6. Structured AI Responses

AI responses are returned in a structured format containing:

-   Text explanation
-   Tables
-   Charts

This ensures results can be easily interpreted, reused, or exported.

------------------------------------------------------------------------

## 7. AI Transparency

For each answer, users can optionally view the raw LLM output used to
generate the response.

This provides transparency and supports debugging or validation of
AI-generated analysis.

------------------------------------------------------------------------

## 8. Application Layout

The application must use a two-area layout consisting of a **left
settings sidebar** and a **main workspace panel**.

### Settings Sidebar (Left Panel)

The left sidebar provides configuration options for the Talk2Excel
session and must include:

-   OpenAI API Key input field
-   Model selection (default: GPT-5.4)
-   Option to securely store the API key on the device
-   Toggle to show raw LLM output used to generate the response
-   Button to clear the conversation

### Main Workspace (Center Panel)

The main panel is used for data interaction and conversational analysis
and contains:

-   Excel upload component
-   Data schema status area
-   Chat interface

The upload component must appear above the chat interface so users load
a dataset before starting the conversation.

------------------------------------------------------------------------

# Technical Constraints (Implementation Guidance)

The application should be implemented using **Python programming
language** and **Streamlit framework**.

The system should reuse the provided prototype code:

-   `talk_2_excel.html`
-   `df_schema.py`
-   `utils.py`

Adhere to the approach in `talk_2_excel.html` --- use **LLM-generated
Python code to analyze the Pandas DataFrame locally**.

Schema generation must use:

``` python
df_schema.make_schema_from_df
```

Automated **end-to-end UI testing** should be implemented using
**Playwright**.

Important: The LLM must be used in end-to-end UI testing — do not shortcut the behavior with deterministic hardcoding. 

Tip: Set Playwright’s default timeout to 30 seconds to ensure faster test iteration.

After all tests pass, the Python codebase must be validated using
**Ruff** as a static code checker and linter.

The job is considered complete only if the codebase passes **Ruff
checks**.

------------------------------------------------------------------------

# Final Delivery Report

Final delivery report must be provided as an HTML file:

    build_report.html

The report should include:

-   Total execution time (start to completion)
-   Lines of code (LOC) added or modified
-   Number of retries or failed runs
-   Summary of completed work
-   Tests and checks executed, including their results
-   Assumptions made during implementation
-   Known issues, limitations, or follow-up work

------------------------------------------------------------------------

# Acceptance Criteria

The system is considered successful if the following conditions are met:

### 1. OpenAI Connectivity

The application can successfully connect to the OpenAI API using a valid
API key.

### 2. Excel Upload

The Excel file:

    data/sample_superstore.xls

can be uploaded and the schema of the uploaded file is displayed
correctly.

### 3. Orders Count

Query:

    Show the number of all orders

Expected result:

    10194

### 4. Top Customers

Query:

    List the top 10 customers by total sales

Expected result:

-   Returns **10 records**
-   Top customer: **Sean Miller**

### 5. West Region Profit

Query:

    Show total profit in the West region

Expected result:

    110,799 (rounded)

### 6. Sales by Sub‑Category

Query:

    Show total sales by sub-category in the Technology category as a table and chart

Expected result inludes a table and and matplotlib chart:

    Phones        $331,843
    Machines      $189,925
    Accessories   $167,380
    Copiers       $150,745

### 7. Highest Profit Product

Query:

    Which product generated the highest total profit?

Expected result:

    Canon imageCLASS 2200 Advanced Copier    25,200
