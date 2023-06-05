import re
import os
import json
import openai
import tkinter as tk
from time import time, sleep
from uuid import uuid4
import datetime
from threading import Thread
from tkinter import ttk, scrolledtext
import pinecone
from dotenv import load_dotenv


##### simple helper functions
payload = []

def open_file(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as infile:
        return infile.read()


def save_file(filepath, content):
    with open(filepath, 'w', encoding='utf-8') as outfile:
        outfile.write(content)


def load_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as infile:
        return json.load(infile)


def save_json(filepath, payload):
    with open(filepath, 'w', encoding='utf-8') as outfile:
        json.dump(payload, outfile, ensure_ascii=False, sort_keys=True, indent=2)

def timestamp_to_datetime(unix_time):
    return datetime.datetime.fromtimestamp(unix_time).strftime("%A, %B %d, %Y at %I:%M%p %Z")


def gpt3_embedding(content, engine='text-embedding-ada-002'):
    content = content.encode(encoding='ASCII',errors='ignore').decode()  # fix any UNICODE errors
    response = openai.Embedding.create(input=content,engine=engine)
    vector = response['data'][0]['embedding']  # this is a normal list
    return vector

def chatgpt_completion(messages, model="gpt-4"):
    max_retry = 7
    retry = 0
    while True:
        try:
            response = openai.ChatCompletion.create(model=model, messages=messages)
            text = response['choices'][0]['message']['content']
            filename = 'chat_%s_muse.txt' % time()
            if not os.path.exists('chat_logs'):
                os.makedirs('chat_logs')
            save_file('chat_logs/%s' % filename, text)
            return text
        except Exception as oops:
            print('\n\n\n OPENAI ERROR:', str(oops), '\n\n\n')
            if 'maximum context length' in str(oops):
                a = messages.pop(1)
                continue
            retry += 1
            if retry >= max_retry:
                print(f"Exiting due to an error in ChatGPT: {oops}")
                exit(1)
            print(f'Error communicating with OpenAI: "{oops}" - Retrying in {2 ** (retry - 1) * 5} seconds...')
            sleep(2 ** (retry - 1) * 5)

def load_conversation(results):
    result = list()
    for m in results['matches']:
        info = load_json('nexus/%s.json' % m['id'])
        result.append(info)
    ordered = sorted(result, key=lambda d: d['time'], reverse=False)  # sort them all chronologically
    messages = [i['message'] for i in ordered]
    return '\n'.join(messages).strip()


def search_conversation(message, convo_length=30):
    global payload
    # Reset payload to an empty list each time this function is called
    payload = list()

    timestamp = time()
    timestring = timestamp_to_datetime(timestamp)

    vector = gpt3_embedding(message)
    unique_id = str(uuid4())
    metadata = {'speaker': 'USER', 'time': timestamp, 'message': message, 'timestring': timestring, 'uuid': unique_id}
    save_json('nexus/%s.json' % unique_id, metadata)
    payload.append((unique_id, vector))
    #### search for relevant messages, and generate a response
    results = vdb.query(vector=vector, top_k=convo_length)
    return load_conversation(results) # results should be a DICT with 'matches' which is a LIST of DICTS, with 'id'

def send_message(event=None):
    user_input = user_entry.get("1.0", tk.END).strip()
    if not user_input.strip():
        return

    chat_text.config(state='normal')
    chat_text.insert(tk.END, f"\n\nUSER:\n{user_input}\n\n", 'user')
    chat_text.see(tk.END)
    chat_text.config(state='disabled')

    user_entry.delete("1.0", tk.END)  # Clear user_entry content

    # Disable input and button while MUSE is thinking
    user_entry.config(state='disabled')
    send_button.config(state='disabled')

    context = search_conversation(user_input, convo_length=convo_length)
    system_message = open_file('default_system_tmp.txt').replace('<<CONVERSATION>>', context)
    conversation[0] = {'role': 'system', 'content': system_message}

    conversation.append({'role': 'user', 'content': user_input})
    filename = 'chat_%s_user.txt' % time()
    if not os.path.exists('chat_logs'):
        os.makedirs('chat_logs')
    save_file('chat_logs/%s' % filename, user_input)

    ai_status.set("MUSE is thinking...")
    Thread(target=get_ai_response).start()
    # Re-enable input and button after response
    user_entry.config(state='normal')
    send_button.config(state='normal')


def get_ai_response():
    global payload

    response = chatgpt_completion(conversation)
    conversation.append({'role': 'assistant', 'content': response})
    # save debug
    filename = 'debug/log_%s_main.json' % time()
    save_json(filename, conversation)

    # Generate a new vector for the assistant's response
    vector = gpt3_embedding(response)
    timestamp = time()
    timestring = timestamp_to_datetime(timestamp)
    unique_id = str(uuid4())
    # Create metadata for the assistant's response
    metadata = {'speaker': 'MUSE', 'time': timestamp, 'message': response, 'timestring': timestring, 'uuid': unique_id}
    save_json('nexus/%s.json' % unique_id, metadata)
    # Append the new vector and unique_id to the payload
    payload.append((unique_id, vector))
    # Upsert the payload to Pinecone
    vdb.upsert(payload)

    def update_chat_text():
        chat_text.config(state='normal')
        chat_text.insert(tk.END, f"\n\nMUSE:\n{response}\n\n", 'muse')
        chat_text.see(tk.END)
        chat_text.config(state='disabled')
        ai_status.set("")

    # Update the chat_text in the main thread
    root.after(0, update_chat_text)



def on_return_key(event):
    if event.state & 0x1:  # Shift key is pressed
        user_entry.insert(tk.END, '\n')
    else:
        send_message()


if __name__ == "__main__":
    load_dotenv()
    convo_length = 30
    openai.api_key = os.environ.get("OPENAI_API_KEY")
    pinecone.init(api_key=os.environ['PINECONE_API_KEY'], environment='us-west4-gcp-free')
    vdb = pinecone.Index("personal-bot")
    scratchpad = open_file('scratchpad.txt')
    system_message = open_file('default_system.txt').replace('<<INPUT>>', scratchpad)
    save_file('default_system_tmp.txt', system_message)
    conversation = list()
    conversation.append({'role': 'system', 'content': system_message})

    # Tkinter GUI
    root = tk.Tk()
    root.title("AutoMuse")

    main_frame = ttk.Frame(root, padding="10")
    main_frame.grid(column=0, row=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    main_frame.columnconfigure(0, weight=1)
    main_frame.rowconfigure(0, weight=1)

    chat_text = tk.Text(main_frame, wrap=tk.WORD, width=60, height=20)
    chat_text.grid(column=0, row=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S))
    chat_text.tag_configure('user', background='#D0F0C0', wrap='word')
    chat_text.tag_configure('muse', background='#AED6F1', wrap='word')
    chat_text.insert(tk.END, "Welcome to AutoMuse!\n\n")
    chat_text.config(state='disabled')

    user_text = tk.StringVar()
    # Replace the Entry widget with a Text widget
    user_entry = tk.Text(main_frame, wrap=tk.WORD, width=50, height=3)
    user_entry.grid(column=0, row=1, sticky=(tk.W, tk.E, tk.N, tk.S))

    send_button = ttk.Button(main_frame, text="Send", command=send_message)
    send_button.grid(column=1, row=1, sticky=(tk.W, tk.E, tk.N, tk.S))

    ai_status = tk.StringVar()
    ai_status_label = ttk.Label(main_frame, textvariable=ai_status)
    ai_status_label.grid(column=2, row=1, sticky=(tk.W, tk.E, tk.N, tk.S))

    user_entry.focus()
    # Update the event binding to use the new Text widget
    root.bind("<Return>", on_return_key)
    # Update the event binding for the user_entry Text widget
    #user_entry.bind("<Return>", on_return_key)

    root.mainloop()