# Email Summarizer

A Python script that processes email conversations, groups them by threads, and generates AI-powered summaries using OpenAI's GPT models.

## Features

- Groups emails by conversation thread (using `conversationId` and date)
- Generates concise summaries for each thread using LLM
- Identifies students and guardians from a CSV file
- Exports summaries to Excel
- Supports dry-run mode for testing without API calls

## Requirements

- Python 3.8+
- Dependencies:
  - `openai`
  - `pandas`
  - `openpyxl`

Install dependencies:
```bash
pip install openai pandas openpyxl
```

## Configuration

Create a `config.json` file (required) with your OpenAI API credentials:

```json
{
    "API_KEY": "your-api-key-here",
    "OPENAI_API_BASE": "https://api.openai.com/v1"
}
```

| Key | Description |
|-----|-------------|
| `API_KEY` | Your OpenAI API key (required) |
| `OPENAI_API_BASE` | API base URL (required) - use `https://api.openai.com/v1` for OpenAI |

See `config.example.json` for a template. Copy it to `config.json` and fill in your credentials.

## Input Files

### emails.json
JSON file containing an array of emails:

```json
[
  {"receivedDateTime": "...", "subject": "...", "body": "...", ...},
  {"receivedDateTime": "...", "subject": "...", "body": "...", ...}
]
```

### alunos.csv
CSV file with student and guardian information:

```csv
nome_aluno,encarregado_de_educacao,email_encarregado
Student Name,Guardian Name,guardian@email.com
```

See `alunos.example.csv` for a sample file.

## Usage

### Basic usage
```bash
python summarize_emails.py emails.json --user-email teacher@school.edu
```

### Command line options

| Option | Description |
|--------|-------------|
| `input_file` | Path to JSON file with emails (required except for --export-excel) |
| `--user-email EMAIL` | Email address of the user (teacher) for perspective in summaries (required for processing) |
| `--force` | Force regeneration of summaries even if they already exist |
| `--limit N`, `-l N` | Process only first N threads |
| `--startdate DATE`, `-s DATE` | Only process threads from this date onwards (YYYY-MM-DD) |
| `--export-excel` | Export summaries to Excel file |
| `--excel-output FILE` | Path for Excel output file (default: resumos.xlsx) |
| `--dry-run` | Simulate without calling LLM (uses random strings) |

### Examples

```bash
# Group and summarize all threads
python summarize_emails.py emails.json --user-email teacher@school.edu

# Process only first 10 threads
python summarize_emails.py emails.json --user-email teacher@school.edu --limit 10

# Process threads from December 2025 onwards
python summarize_emails.py emails.json --user-email teacher@school.edu --startdate 2025-12-01

# Regenerate all summaries
python summarize_emails.py emails.json --user-email teacher@school.edu --force

# Export existing summaries to Excel (no --user-email needed)
python summarize_emails.py --export-excel

# Test without calling LLM
python summarize_emails.py emails.json --user-email teacher@school.edu --dry-run
```

## Output Files

### email_threads.json
JSON file with grouped email threads and summaries:

```json
{
  "total_threads": 100,
  "total_emails": 250,
  "threads": [
    {
      "conversation_id": "...",
      "date": "2025-12-01",
      "thread_subject": "Subject",
      "participants": ["email1@...", "email2@..."],
      "email_count": 3,
      "summary": "Summary text...",
      "emails": [...]
    }
  ]
}
```

### resumos.xlsx
Excel file with two columns:
- **Data e Hora**: Timestamp of the first email in the thread
- **Resumo**: Generated summary

If the file already exists, a numbered version is created (resumos_1.xlsx, resumos_2.xlsx, etc.)

## How it works

1. **Load emails** from JSON file
2. **Group by thread** using `conversationId` and date
3. **Clean email content**: Remove HTML, external warnings, and quoted headers
4. **Generate summaries** using OpenAI GPT model
5. **Export to Excel** automatically

## LLM Configuration

- Model: `gpt-4o-mini`
- Temperature: `0.2` (low for fewer hallucinations)
- Max tokens: `130`

The system prompt instructs the LLM to:
- Summarize from the teacher's perspective
- Use guardian/student names correctly
- Ignore thank you messages, holiday wishes, and quoted content
- Mark irrelevant threads as `[NÃO RELEVANTE]`

