# dark-software-factory
Tests and benchmarks to address one simple question: Dark Software Factory - how far are we from it?

Inspired by Dan Shapiro’s article [The Five Levels: From Spicy Autocomplete to the Software Factory](https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/), this project explores a simple but fascinating question:

> **How far are we from the Dark Software Factory — a black box that turns specs into production software?**

## The Five Levels of Agentic Automation
Below is the conceptual ladder from AI-assisted coding to fully autonomous software generation.

![Five Levels of Agentic Automation](images/agentic_levels.png)

Quick summary:

| Level                         | Description                                         | Human Role                          |
| ----------------------------- | --------------------------------------------------- | ----------------------------------- |
| **1 — Coding Intern**         | AI helps with small prompts and tasks               | Direct prompting                    |
| **2 — Junior Developer**      | Pair programming with AI                            | Continuous interaction              |
| **3 — Developer**             | AI writes code, humans review                       | Mostly synchronous supervision      |
| **4 — Engineering Team**      | Spec-driven development with automated checks       | Humans define specs                 |
| **5 — Dark Software Factory** | A black box that turns specifications into software | Humans define what, not how         |

This project tests whether we can reliably operate somewhere between Level 4 and Level 5.

## The Experiment

To test the reliability of **specification-driven development**, here is a simple challenge:

### Build a small application called **Talk2Excel**

The app allows users to:

- Upload large Excel files  
- Ask questions in natural language  
- Analyze data **locally** without uploading sensitive data to an LLM  

Instead of sending the data to the model, the system works like this:

```text
User question
    ↓
Prompt (user question + spreadsheet schema)
    ↓
LLM generates Python code
    ↓
Python runs locally on the dataframe
    ↓
Results returned to user
```

