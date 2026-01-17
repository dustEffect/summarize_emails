import json
import re
import time
import argparse
import os
import random
import string
from datetime import datetime
from html.parser import HTMLParser
from openai import OpenAI
import pandas as pd


# Load configuration
def load_config(config_path: str = 'config.json') -> dict:
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        print(f"Error: Configuration file '{config_path}' not found.")
        print("Please create a config.json file with the following content:")
        print('''
{
    "API_KEY": "your-api-key-here",
    "OPENAI_API_BASE": "https://api.openai.com/v1"
}
''')
        print("See config.example.json for reference.")
        exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Validate required keys
    required_keys = ['API_KEY', 'OPENAI_API_BASE']
    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        print(f"Error: Missing required keys in config.json: {', '.join(missing_keys)}")
        exit(1)
    
    return config


# Initialize OpenAI client
config = load_config()
client = OpenAI(
    api_key=config['API_KEY'],
    base_url=config['OPENAI_API_BASE']
)


def load_alunos(csv_path: str = 'alunos.csv') -> pd.DataFrame:
    """Load students data from CSV file."""
    if not os.path.exists(csv_path):
        print(f"\n⚠️  WARNING: File '{csv_path}' not found.")
        print("   Summaries may lack proper student/guardian name identification.")
        print("   See alunos.example.csv for the expected format.\n")
        return pd.DataFrame(columns=['nome_aluno', 'encarregado_de_educacao', 'emails_encarregado'])
    
    df = pd.read_csv(csv_path)
    
    if df.empty:
        print(f"\n⚠️  WARNING: File '{csv_path}' is empty.")
        print("   Summaries may lack proper student/guardian name identification.\n")
        return pd.DataFrame(columns=['nome_aluno', 'encarregado_de_educacao', 'emails_encarregado'])
    
    # Group by student and guardian, aggregating emails into a list
    df = df.groupby(['nome_aluno', 'encarregado_de_educacao'])['email_encarregado'].apply(list).reset_index()
    df.columns = ['nome_aluno', 'encarregado_de_educacao', 'emails_encarregado']
    
    return df


# Load students dataframe
df_alunos = load_alunos()


def llm(system_prompt: str, user_prompt: str, model: str = 'gpt-4o-mini', temperature: float = 0.2, max_tokens: int = 130) -> str:
    """
    Send prompts to the LLM and return the response.
    
    Args:
        system_prompt: Instructions for the model's behavior
        user_prompt: The user's message/question
        model: The model to use (default: gpt-4o-mini)
        temperature: Controls randomness (0.0 = deterministic, 1.0 = creative). Lower = fewer hallucinations.
        max_tokens: Maximum number of tokens in the response (default: 130)
    
    Returns:
        The model's response as a string
    """
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )
    return response.choices[0].message.content


class HTMLStripper(HTMLParser):
    """HTML parser that extracts text content only."""
    
    def __init__(self):
        super().__init__()
        self.reset()
        self.text = []
    
    def handle_data(self, data):
        self.text.append(data)
    
    def get_text(self):
        return ''.join(self.text)


def strip_html(html_content: str) -> str:
    """Remove HTML tags, CSS comments, and return plain text."""
    if not html_content:
        return ""
    
    # Remove HTML comments (including CSS in comments)
    html_content = re.sub(r'<!--.*?-->', '', html_content, flags=re.DOTALL)
    
    # Remove style tags and their content
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    
    # Strip HTML tags
    stripper = HTMLStripper()
    stripper.feed(html_content)
    text = stripper.get_text()
    
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def normalize_subject(subject: str) -> str:
    """Normalize email subject by removing Re:, Fwd:, etc."""
    if not subject:
        return ""
    # Remove common prefixes (case insensitive)
    normalized = re.sub(r'^(re:|fwd:|fw:|enc:|res:|rv:)\s*', '', subject.strip(), flags=re.IGNORECASE)
    # Recursively remove if there are multiple prefixes
    while normalized != subject:
        subject = normalized
        normalized = re.sub(r'^(re:|fwd:|fw:|enc:|res:|rv:)\s*', '', subject.strip(), flags=re.IGNORECASE)
    return normalized.strip()


def get_thread_key(email: dict) -> str:
    """Generate a unique key for email thread using conversationId."""
    # Use Microsoft's conversationId which tracks the actual thread
    return email.get('conversationId', '')


def get_participants(email: dict) -> set:
    """Extract all participants (from and to) from an email."""
    participants = set()
    from_addr = email.get('from', '')
    if from_addr:
        participants.add(from_addr.lower())
    
    to_addr = email.get('toRecipients', '')
    if to_addr:
        # Handle multiple recipients separated by semicolon
        for addr in to_addr.split(';'):
            addr = addr.strip().lower()
            if addr:
                participants.add(addr)
    
    return participants


def get_date_from_datetime(datetime_str: str) -> str:
    """Extract date (YYYY-MM-DD) from ISO datetime string."""
    if not datetime_str:
        return ""
    try:
        dt = datetime.fromisoformat(datetime_str.replace('+00:00', '+00:00').replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d')
    except:
        return datetime_str[:10] if len(datetime_str) >= 10 else ""


def clean_email(email: dict) -> dict:
    """Remove unnecessary fields from email and add plainTextBody."""
    fields_to_remove = ['attachments', 'isRead', 'isHtml', 'hasAttachments', 'body', 'id', 'internetMessageId', 'importance', 'bodyPreview']
    cleaned = {k: v for k, v in email.items() if k not in fields_to_remove}
    
    # Add plainTextBody
    plain_text = strip_html(email.get('body', ''))
    
    # Remove external email warning
    external_warning = "[ATENÇÃO] Este email teve origem fora da sua organização. Não clique em links ou abra anexos, a menos que reconheça o remetente e saiba que o conteúdo é seguro."
    plain_text = plain_text.replace(external_warning, '').strip()
    
    # Remove quoted email headers
    plain_text = re.sub(r'De:.*?<[^>]+@[^>]+>.*?Enviado:.*?Para:.*?<[^>]+@[^>]+>.*$', '', plain_text, flags=re.DOTALL)
    plain_text = re.sub(r'From:.*?<[^>]+@[^>]+>.*?Sent:.*?To:.*?<[^>]+@[^>]+>.*$', '', plain_text, flags=re.DOTALL)
    plain_text = plain_text.strip()
    
    cleaned['plainTextBody'] = plain_text
    
    return cleaned


def group_emails_by_thread(input_path: str, output_path: str = 'email_threads.json', startdate: str = None) -> dict:
    """Group emails by conversation thread using conversationId AND date."""
    
    # Load JSON file
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    emails = data
    
    # Filter by startdate if specified
    if startdate:
        emails = [e for e in emails if get_date_from_datetime(e.get('receivedDateTime', '')) >= startdate]
        print(f"Filtered to {len(emails)} emails from {startdate} onwards")
    
    # Group emails by conversationId + date
    threads = {}
    for email in emails:
        conversation_id = email.get('conversationId', '')
        email_date = get_date_from_datetime(email.get('receivedDateTime', ''))
        
        if not conversation_id:
            # Fallback: create unique key from subject + participants
            participants = tuple(sorted(get_participants(email)))
            subject = normalize_subject(email.get('subject', ''))
            conversation_id = f"{subject}_{hash(participants)}"
        
        # Create thread key combining conversationId and date
        thread_key = f"{conversation_id}_{email_date}"
        
        if thread_key not in threads:
            threads[thread_key] = {
                'conversation_id': conversation_id,
                'date': email_date,
                'thread_subject': normalize_subject(email.get('subject', '')),
                'participants': set(),
                'emails': []
            }
        
        threads[thread_key]['emails'].append(clean_email(email))
        threads[thread_key]['participants'].update(get_participants(email))
    
    # Sort emails within each thread by date (oldest first) and finalize
    for thread in threads.values():
        thread['emails'].sort(key=lambda x: x.get('receivedDateTime', ''))
        thread['email_count'] = len(thread['emails'])
        thread['participants'] = sorted(list(thread['participants']))
        # Update subject from first email in thread
        if thread['emails']:
            thread['thread_subject'] = normalize_subject(thread['emails'][0].get('subject', ''))
    
    # Convert to list and sort by date (oldest first)
    thread_list = list(threads.values())
    thread_list.sort(key=lambda x: x['emails'][0].get('receivedDateTime', ''))
    
    # Create output structure
    output_data = {
        'total_threads': len(thread_list),
        'total_emails': len(emails),
        'threads': thread_list
    }
    
    # Save to file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=3)
    
    print(f"Grouped {len(emails)} emails into {len(thread_list)} threads")
    print(f"Saved to {output_path}")
    
    return output_data


def get_alunos_context() -> str:
    """Generate explicit records for each guardian with student and email info."""
    if df_alunos.empty:
        return "(No student/guardian data available)"
    
    lines = []
    for _, row in df_alunos.iterrows():
        emails = ', '.join(row['emails_encarregado'])
        lines.append(f"{row['encarregado_de_educacao']}, holder of addresses {emails}, is responsible for the student {row['nome_aluno']}")
    return '\n'.join(lines)


def summarize_thread(thread: dict, user_email: str) -> str:
    """Generate a summary of the entire email thread using LLM."""
    
    alunos_context = get_alunos_context()
    
    system_prompt = f"""You are an assistant that summarizes email conversations concisely.
Provide a brief summary in the same language as the emails.
Focus on the main point, request, or outcome of the conversation.

IMPORTANT: The summary must NOT exceed 500 characters.

Important: The email {user_email} belongs to the user (a teacher).
Write the summary from the user's perspective.

USE THE FOLLOWING LIST to correctly identify students and guardians by their FIRST and LAST NAME (not email addresses):
{alunos_context}

When mentioning people in the summary:
- Do NOT use the guardian's name directly
- Use the expression "Encarregado de Educação do <student name>" or "EE do <student name>" ONLY ONCE at the beginning
- After the first mention, use shorter references like "o/a EE", "ele/ela", or just omit when clear from context
- Use ONLY FIRST and LAST name for students (not full name)
- Example: "Gabriel Guedes Pinto" should be written as "Gabriel Pinto"
- Use the list above to find the student's name from the guardian's email address

IMPORTANT - Infer the guardian's gender from their name to use the correct article:
- Female names (Maria, Ana, Sandra, Mónica, etc.) → "A EE do...", "ela"
- Male names (João, Mário, Pedro, etc.) → "O EE do...", "ele"
- Example: "Mónica Costa" is female → "A EE do Gabriel Pinto informou..."
- Example: "Mário Pinto" is male → "O EE do Gabriel Pinto informou..."

CORRECT example:
- "A EE do Gabriel Pinto informou que o Gabriel faltou por motivo de doença. Pediu justificação das faltas e eu confirmei a receção."

AVOID being repetitive:
- DO NOT write: "A EE do Gabriel Pinto informou... A EE do Gabriel Pinto pediu... A EE do Gabriel Pinto questionou..."

IMPORTANT - Identify who is speaking:
When summarizing, clearly mention who is asking or responding at each point in the conversation.
Use expressions like:
- "O encarregado de educação questionou/informou/pediu <assunto>, e eu respondi que <resposta>"
- "O pai/mãe do aluno perguntou <questão>, ao que eu respondi <resposta>"
- "Recebi um pedido de <assunto> do encarregado de educação, e informei que <resposta>"
- "Após a minha resposta sobre <assunto>, o encarregado questionou se <nova questão>"

The goal is to create a fluent summary where it's clear who is asking and who is responding at each point.

When analyzing the conversation, IGNORE these parts (do not include in summary):
- Thank you messages for responses or for sending something
- Holiday wishes, good week wishes, or similar pleasantries
- Acknowledgment of receipt
- Signatures and automatic footers
- Do NOT mention lack of response or that the conversation had no continuation
- Do NOT say things like "não houve resposta", "sem resposta", "a conversa não teve continuação"
- Do NOT mention when parents/guardians confirm they WILL attend or be present at something
- DO mention when parents/guardians say they will NOT be able to attend (absences are relevant)
- Do NOT mention that people thanked or expressed gratitude (e.g., "agradeceu", "agradeceram")
- Do NOT mention thanks for document delivery, email sending, or concern shown (e.g., "agradeceu o envio", "agradeceu a entrega", "agradeceu a preocupação")
- IGNORE everything that follows "Forwarded message" or "---------- Forwarded message ---------" as it's not relevant
- IGNORE quoted/transcribed content from previous emails (usually appears after "De:", "From:", "Enviado:", "Sent:", "Em <date> escreveu:", "On <date> wrote:")
- Focus ONLY on the NEW content written in each email, not the quoted history

Focus ONLY on relevant information such as:
- Requests or questions
- Important information being communicated
- Actions needed or decisions made
- Outcomes or resolutions

If after ignoring the non-relevant parts there is NO useful information left, respond with exactly "[NÃO RELEVANTE]"."""
    
    # Build conversation context
    conversation = []
    for email in thread.get('emails', []):
        from_email = email.get('from', '')
        to_email = email.get('toRecipients', '')
        body = email.get('plainTextBody', '')
        date = email.get('receivedDateTime', '')[:10]
        
        conversation.append(f"From: {from_email}\nTo: {to_email}\nDate: {date}\n\n{body}")
    
    conversation_text = "\n\n---\n\n".join(conversation)
    user_prompt = f"Subject: {thread.get('thread_subject', '')}\n\nConversation:\n\n{conversation_text}"
    
    try:
        return llm(system_prompt, user_prompt)
    except Exception as e:
        return f"Error generating summary: {str(e)}"


def get_unique_filename(output_path: str) -> str:
    """Generate a unique filename by adding a number if file exists."""
    if not os.path.exists(output_path):
        return output_path
    
    # Split filename and extension
    base, ext = os.path.splitext(output_path)
    
    # Find next available number
    counter = 1
    while os.path.exists(f"{base}_{counter}{ext}"):
        counter += 1
    
    return f"{base}_{counter}{ext}"


def export_to_excel(json_path: str = 'email_threads.json', output_path: str = 'resumos.xlsx') -> None:
    """Export summaries to Excel file."""
    
    # Get unique filename if file exists
    output_path = get_unique_filename(output_path)
    
    # Load grouped emails
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    threads = data.get('threads', [])
    
    # Build data for Excel
    records = []
    for thread in threads:
        # Get date and time from first email in thread
        if thread.get('emails'):
            datetime_str = thread['emails'][0].get('receivedDateTime', '')
        else:
            datetime_str = thread.get('date', '')
        
        summary = thread.get('summary', '')
        
        # Only include threads with summaries
        if summary and summary != '[NÃO RELEVANTE]':
            records.append({
                'Data e Hora': datetime_str,
                'Resumo': summary
            })
    
    # Create DataFrame and export to Excel
    df = pd.DataFrame(records)
    df.to_excel(output_path, index=False)
    
    print(f"Exported {len(records)} summaries to {output_path}")


def generate_random_summary() -> str:
    """Generate a random string for dryrun mode."""
    length = random.randint(50, 150)
    return '[DRYRUN] ' + ''.join(random.choices(string.ascii_letters + ' ', k=length))


def process_thread_summaries(json_path: str = 'email_threads.json', force_summaries: bool = False, limit: int = None, dryrun: bool = False, user_email: str = None) -> None:
    """Process threads and generate summaries for each thread."""
    
    if dryrun:
        print("\n*** DRYRUN MODE - LLM will not be called ***\n")
    
    # Load grouped emails
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    threads = data.get('threads', [])
    
    # Create list of threads to process
    threads_to_process = [(i, t) for i, t in enumerate(threads)]
    
    # Apply limit if specified
    if limit:
        threads_to_process = threads_to_process[:limit]
    
    total = len(threads_to_process)
    
    # Print the system prompt before starting
    if total > 0:
        sample_prompt = summarize_thread.__doc__  # Just to trigger creation
        alunos_context = get_alunos_context()
        print("\n" + "=" * 80)
        print("SYSTEM PROMPT:")
        print("=" * 80)
        # Build and print the system prompt
        system_prompt = f"""You are an assistant that summarizes email conversations concisely.
Provide a brief summary in the same language as the emails.
Focus on the main point, request, or outcome of the conversation.

IMPORTANT: The summary must NOT exceed 500 characters.

Important: The email {user_email} belongs to the user (a teacher).
Write the summary from the user's perspective.

USE THE FOLLOWING LIST to correctly identify students and guardians by their FIRST and LAST NAME (not email addresses):
{alunos_context}

When mentioning people in the summary:
- Do NOT use the guardian's name directly
- Use the expression "Encarregado de Educação do <student name>" or "EE do <student name>" ONLY ONCE at the beginning
- After the first mention, use shorter references like "o/a EE", "ele/ela", or just omit when clear from context
- Use ONLY FIRST and LAST name for students (not full name)
- Example: "Gabriel Guedes Pinto" should be written as "Gabriel Pinto"
- Use the list above to find the student's name from the guardian's email address

IMPORTANT - Infer the guardian's gender from their name to use the correct article:
- Female names (Maria, Ana, Sandra, Mónica, etc.) → "A EE do...", "ela"
- Male names (João, Mário, Pedro, etc.) → "O EE do...", "ele"
- Example: "Mónica Costa" is female → "A EE do Gabriel Pinto informou..."
- Example: "Mário Pinto" is male → "O EE do Gabriel Pinto informou..."

CORRECT example:
- "A EE do Gabriel Pinto informou que o Gabriel faltou por motivo de doença. Pediu justificação das faltas e eu confirmei a receção."

AVOID being repetitive:
- DO NOT write: "A EE do Gabriel Pinto informou... A EE do Gabriel Pinto pediu... A EE do Gabriel Pinto questionou..."

IMPORTANT - Identify who is speaking:
When summarizing, clearly mention who is asking or responding at each point in the conversation.
Use expressions like:
- "O encarregado de educação questionou/informou/pediu <assunto>, e eu respondi que <resposta>"
- "O pai/mãe do aluno perguntou <questão>, ao que eu respondi <resposta>"
- "Recebi um pedido de <assunto> do encarregado de educação, e informei que <resposta>"
- "Após a minha resposta sobre <assunto>, o encarregado questionou se <nova questão>"

The goal is to create a fluent summary where it's clear who is asking and who is responding at each point.

When analyzing the conversation, IGNORE these parts (do not include in summary):
- Thank you messages for responses or for sending something
- Holiday wishes, good week wishes, or similar pleasantries
- Acknowledgment of receipt
- Signatures and automatic footers
- Do NOT mention lack of response or that the conversation had no continuation
- Do NOT say things like "não houve resposta", "sem resposta", "a conversa não teve continuação"
- Do NOT mention when parents/guardians confirm they WILL attend or be present at something
- DO mention when parents/guardians say they will NOT be able to attend (absences are relevant)
- Do NOT mention that people thanked or expressed gratitude (e.g., "agradeceu", "agradeceram")
- Do NOT mention thanks for document delivery, email sending, or concern shown (e.g., "agradeceu o envio", "agradeceu a entrega", "agradeceu a preocupação")
- IGNORE everything that follows "Forwarded message" or "---------- Forwarded message ---------" as it's not relevant
- IGNORE quoted/transcribed content from previous emails (usually appears after "De:", "From:", "Enviado:", "Sent:", "Em <date> escreveu:", "On <date> wrote:")
- Focus ONLY on the NEW content written in each email, not the quoted history

Focus ONLY on relevant information such as:
- Requests or questions
- Important information being communicated
- Actions needed or decisions made
- Outcomes or resolutions

If after ignoring the non-relevant parts there is NO useful information left, respond with exactly "[NÃO RELEVANTE]"."""
        print(system_prompt)
        print("=" * 80 + "\n")
    
    for idx, (original_idx, thread) in enumerate(threads_to_process):
        existing_summary = thread.get('summary', '')
        
        if force_summaries or not existing_summary:
            print(f"Summarizing thread {idx + 1}/{total}: {thread.get('thread_subject', '')[:50]}...")
            if dryrun:
                summary = generate_random_summary()
            else:
                summary = summarize_thread(thread, user_email)
            
            # Save summary to thread
            data['threads'][original_idx]['summary'] = summary
            
            # Save to file after each summary
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=3)
            
            # Wait 3 seconds before next thread (skip in dry-run mode)
            if idx < total - 1 and not dryrun:
                time.sleep(3)
    
    print(f"\nProcessed {total} threads")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Process emails from JSON file, group by threads, and generate summaries using LLM.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python summarize_emails.py emails.json --user-email teacher@school.edu                    # Group and summarize all threads
  python summarize_emails.py emails.json --user-email teacher@school.edu --limit 10         # Process only first 10 threads
  python summarize_emails.py emails.json --user-email teacher@school.edu -s 2025-12-01      # Process from this date onwards
  python summarize_emails.py emails.json --user-email teacher@school.edu --force            # Regenerate all summaries
  python summarize_emails.py --export-excel                                                 # Export summaries to Excel
  python summarize_emails.py emails.json --user-email teacher@school.edu --dry-run          # Test without calling LLM
        '''
    )
    
    parser.add_argument(
        'input_file',
        type=str,
        nargs='?',
        default=None,
        help='Path to the JSON file with emails (required except for --export-excel)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force regeneration of summaries even if they already exist'
    )
    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=None,
        help='Maximum number of threads to process'
    )
    parser.add_argument(
        '--startdate', '-s',
        type=str,
        default=None,
        help='Only process threads from this date onwards (format: YYYY-MM-DD)'
    )
    parser.add_argument(
        '--export-excel',
        action='store_true',
        help='Export summaries to Excel file (resumos.xlsx)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate the process without calling LLM (uses random strings as summaries)'
    )
    parser.add_argument(
        '--excel-output',
        type=str,
        default='resumos.xlsx',
        help='Path for Excel output file (default: resumos.xlsx)'
    )
    parser.add_argument(
        '--user-email',
        type=str,
        default=None,
        help='Email address of the user (teacher) for perspective in summaries (required for processing)'
    )
    
    args = parser.parse_args()
    
    # If only exporting to Excel, check if email_threads.json exists and export
    threads_file = 'email_threads.json'
    
    if args.export_excel and not args.dry_run:
        if not os.path.exists(threads_file):
            print(f"Error: '{threads_file}' not found. Run the script first to generate summaries.")
            exit(1)
        export_to_excel(threads_file, args.excel_output)
        exit(0)
    
    # Validate user-email is provided for processing
    if not args.user_email:
        print("Error: --user-email is required when processing emails.")
        parser.print_usage()
        exit(1)
    
    # Validate input file is provided and exists
    if not args.input_file:
        print("Error: input_file is required.")
        parser.print_usage()
        exit(1)
    
    if not os.path.exists(args.input_file):
        print(f"Error: Input file '{args.input_file}' not found.")
        exit(1)
    
    # Check if email_threads.json already exists and has content
    needs_grouping = True
    
    if os.path.exists(threads_file):
        try:
            with open(threads_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            if existing_data.get('threads') and len(existing_data['threads']) > 0:
                print(f"Using existing {threads_file} with {len(existing_data['threads'])} threads")
                needs_grouping = False
        except:
            pass
    
    if needs_grouping:
        group_emails_by_thread(args.input_file, threads_file, startdate=args.startdate)
    
    # Generate summaries
    process_thread_summaries(
        json_path='email_threads.json',
        force_summaries=args.force,
        limit=args.limit,
        dryrun=args.dry_run,
        user_email=args.user_email
    )
    
    # Always export to Excel at the end
    export_to_excel('email_threads.json', args.excel_output)
    
    # Display threads
    with open('email_threads.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"\nTotal threads: {data['total_threads']}\n")
    print("=" * 80)
    
    for idx, thread in enumerate(data['threads']):
        print(f"Thread #{idx + 1}")
        print("-" * 40)
        print(f"date:         {thread.get('date', '')}")
        print(f"subject:      {thread.get('thread_subject', '')}")
        print(f"participants: {', '.join(thread.get('participants', []))}")
        print(f"email_count:  {thread.get('email_count', 0)}")
        print(f"summary:      {thread.get('summary', '')}")
        print("=" * 80)
