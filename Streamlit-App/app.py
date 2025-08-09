import streamlit as st
import boto3
from fpdf import FPDF
import hashlib
import sqlite3
import assemblyai as aai
import json
from pytube import YouTube
from dotenv import load_dotenv
import os

load_dotenv()  

api_key = os.getenv('AAI_API_KEY')
aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
s3_bucket_name = os.getenv('S3_BUCKET_NAME')

lambda_client = boto3.client('lambda', region_name='us-east-1')

# Establishing SQLite connection
conn = sqlite3.connect('users.db', check_same_thread=False)
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        username TEXT NOT NULL PRIMARY KEY,
        password TEXT NOT NULL
    )
''')
conn.commit()

def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def verify_password(stored_password, provided_password):
    return stored_password == hash_password(provided_password)

def add_user_to_db(username, password):
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hash_password(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def check_user_in_db(username, password):
    c.execute("SELECT password FROM users WHERE username = ?", (username,))
    result = c.fetchone()
    if result and verify_password(result[0], password):
        return True
    return False

def transcribe_audio(file_path):
     transcriber = aai.Transcriber()
     config = aai.TranscriptionConfig(speaker_labels=True)
     transcript = transcriber.transcribe(file_path, config=config)
     if transcript is not None and transcript.utterances:
        return " ".join(utterance.text for utterance in transcript.utterances)
     else:
        return "No transcription available."

def text_to_pdf(text, filename):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, text)
    pdf_path = f"{filename.rsplit('.', 1)[0]}.pdf"  
    pdf.output(pdf_path)
    return pdf_path


def upload_to_s3(file_path, object_name, user_id):
    s3_client = boto3.client(
        's3',
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key
    )
    object_name = object_name.rsplit('.', 1)[0] + '.pdf'
    object_name_with_user = f"{user_id}+{object_name}"
    s3_client.upload_file(file_path, s3_bucket_name, object_name_with_user)
    return True

def call_lambda_function(user_id):
    lambda_function_name = 'getalldocuments'
    response = lambda_client.invoke(
        FunctionName=lambda_function_name,
        InvocationType='RequestResponse',
        Payload=json.dumps({"requestContext": {"authorizer": {"claims": {"sub": user_id}}}})
    )
    result = json.loads(response['Payload'].read().decode('utf-8'))
    return result

def handle_ready_to_chat(document_id, conversation_id):
    # Display the document ID and conversation ID
    st.write(f"Document ID: {document_id}")
    st.write(f"Conversation ID: {conversation_id}")

    # Add a button to start a new conversation
    if st.button("Start New Conversation"):
        # Call your add_conversation lambda function here
        add_conversation_response = call_add_conversation_lambda(document_id)
        
        # Handle the response from the add_conversation lambda function
        if add_conversation_response['statusCode'] == 200:
            new_conversation_id = add_conversation_response['body']
            st.success(f"New conversation created with ID: {new_conversation_id}")
            # Update the conversation_id in the session state
            st.session_state.selected_document['conversation_id'] = new_conversation_id
            # Prompt the user to navigate to the chat section
            st.info("Navigate to the chat section to start the conversation.")
        else:
            st.error(f"Error creating new conversation: {add_conversation_response['body']}")



# Adjust the function to take a single dictionary argument
def display_document_details(filename, filesize, pages, document_id, conversation_id):
    """
    Display a tile with document details below the menu.
    """
    with st.container():
        st.write(f"**Filename:** {filename}")
        st.write(f"**Filesize:** {filesize} KB")
        st.write(f"**Pages:** {pages}")
        # st.write(f"**Document ID:** {document_id}")
        # st.write(f"**Conversation ID:** {conversation_id}")

def get_response(user_id, file_name, human_input, conversation_id):
    lambda_function_name = 'test-generate_response'
    body = {
        "fileName": file_name,
        "prompt": human_input,
        "conversationid": conversation_id,
        "inputText": human_input,
        "textGenerationConfig": {
            "maxTokenCount": 8192,
            "stopSequences": [],
            "temperature": 0.1,
            "topP": 1
        }
    }
    response = lambda_client.invoke(
        FunctionName=lambda_function_name,
        InvocationType='RequestResponse',
        Payload=json.dumps({
            "body": body,
            "pathParameters": {
                "conversationid": conversation_id
            },
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "sub": user_id
                    }
                }
            }
        })
    )
    result = json.loads(response['Payload'].read().decode('utf-8'))
    print(result)
    return result

    
    result = json.loads(response['Payload'].read().decode('utf-8'))
    print(result)
    return result

def display_document_card(document):
    col1, col2, col3, col4 = st.columns([2, 1, 2, 1])
    with col1:
        st.text(f"Filename: {document['filename']}")
    with col2:
        st.text(f"Filesize: {document['filesize']} KB")
    with col3:
        st.text(f"Pages: {document['pages']} Pages")
    with col4:
        if st.button("Ready to chat", key=document['documentid'], on_click=handle_ready_to_chat, args=(document['documentid'], document['conversations'][0]['conversationid'])):
            # When the button is clicked, store the document details in session state
            st.session_state.selected_document = {
                "filename": document['filename'],
                "filesize": document['filesize'],
                "pages": document['pages'],
                "document_id": document['documentid'],
                "conversation_id": document['conversations'][0]['conversationid']
            }
def fetch_documents(user_id):
    result = call_lambda_function(user_id)
    documents = json.loads(result.get('body', '{}'))
    if documents:
        for document in documents:
            display_document_card(document)
    else:
        st.write("No documents found. Please upload a document.")
def call_add_conversation_lambda(document_id):
    lambda_function_name = 'add_conversation'
    user_id = st.session_state['user_id']
    response = lambda_client.invoke(
        FunctionName=lambda_function_name,
        InvocationType='RequestResponse',
        Payload=json.dumps({
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "sub": user_id
                    }
                }
            },
            "pathParameters": {
                "documentid": document_id
            }
        })
    )
    result = json.loads(response['Payload'].read().decode('utf-8'))
    return result

def download_youtube_audio(yt_url):
    yt = YouTube(yt_url)
    audio_stream = yt.streams.filter(only_audio=True).first()
    audio_path = audio_stream.download(output_path='downloads/')
    return audio_path


def transcribe_and_handle_audio(audio_path):
    # Transcribe the audio to text
    transcript = transcribe_audio(audio_path)
    st.text_area("Transcript", transcript, height=300)
    
    # Extract the base filename from the path, without the extension
    base_filename = audio_path.split('/')[-1].rsplit('.', 1)[0]
    
    # Create the PDF file name as "user_id+filename.pdf"
    user_id = st.session_state['user_id']
    pdf_file_name = f"{base_filename}.pdf"
    
    # Generate the PDF file
    pdf_path = text_to_pdf(transcript, pdf_file_name)
    
    # Upload the PDF to S3 with the desired naming convention
    if upload_to_s3(pdf_path, pdf_file_name, user_id):
        st.success(f"File {pdf_path} uploaded successfully to {s3_bucket_name}")


def custom_css():
    st.markdown("""
    <style>
    .stTextInput>div>div>input, .stTextArea>textarea {
        border-radius: 20px;
        padding: 10px;
    }
    .stButton>button {
        border-radius: 20px;
        border: 2px solid #6c4fbb;
        background-color: #6c4fbb;
        color: white;
        padding: 10px 24px;
        font-size: 16px;
        line-height: 20px;
        width: 100%;
        cursor: pointer;
    }
    .stMarkdown>div {
        font-size: 16px;
    }
    </style>
    """, unsafe_allow_html=True)


def clean_chat_response(text):
    return text.replace("\\n","").strip()



def main():
    custom_css()
    st.title('VOICE IQ')
    st.subheader('Revolutionizing Content Management and Intelligent Interaction')
    st.image("C:/Users/19452/Desktop/UIDOSC/logo_viq (2).png", width=100)  # Adjust path as necessary

    if 'messages' not in st.session_state:
        st.session_state.messages = []

    menu = ["Login", "SignUp", "Transcribe and Upload", "My Files", "Chat"]
    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Login":
        username = st.sidebar.text_input("Username")
        password = st.sidebar.text_input("Password", type='password')
        if st.sidebar.button("Login"):
            if check_user_in_db(username, password):
                st.session_state['user_id'] = username
                st.success(f"Logged In as {username}")
            else:
                st.error("Incorrect username or password")
    elif choice == "SignUp":
        new_user = st.sidebar.text_input("New Username")
        new_password = st.sidebar.text_input("New Password", type='password')
        confirm_password = st.sidebar.text_input("Confirm Password", type='password')
        if st.sidebar.button("Create Account"):
            if new_password == confirm_password:
                if add_user_to_db(new_user, new_password):
                    st.session_state['user_id'] = new_user
                    st.success("Account created successfully")
                else:
                    st.error("Username already exists")
            else:
                st.error("Passwords do not match")

    if 'user_id' in st.session_state and choice == "Transcribe and Upload":
        upload_option = st.radio("Upload Method", ["Upload MP3", "YouTube Link"])
        if upload_option == "Upload MP3":
            audio_file = st.file_uploader("Upload your MP3 file", type=['mp3'])
            if audio_file and st.button('Transcribe and Upload'):
                audio_path = audio_file.name
                with open(audio_path, "wb") as f:
                    f.write(audio_file.getbuffer())
                transcript = transcribe_and_handle_audio(audio_path)
        elif upload_option == "YouTube Link":
            yt_url = st.text_input("Enter YouTube URL")
            if st.button('Download and Transcribe'):
                with st.spinner('Downloading YouTube audio...'):
                    audio_path = download_youtube_audio(yt_url)
                transcript = transcribe_and_handle_audio(audio_path)

    if choice == "My Files":
        if 'user_id' in st.session_state:
            fetch_documents(st.session_state['user_id'])
        if 'selected_document' in st.session_state:
            display_document_details(**st.session_state.selected_document)
  
    if choice == "Chat":
        if 'selected_document' in st.session_state:
            display_document_details(**st.session_state.selected_document)
            document_id = st.session_state.selected_document['document_id']
            conversation_id = st.session_state.selected_document['conversation_id']
            human_input = st.chat_input("Your message")

            if "messages" not in st.session_state:
                st.session_state.messages = []

            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            
            if human_input:
                user_message = {
                    "role": "user",
                    "content": human_input
                }
                st.chat_message("user").markdown(human_input)
                st.session_state.messages.append(user_message)

                user_id = st.session_state['user_id']
                file_name = f"{user_id}+{st.session_state.selected_document['filename']}"

                # Assuming the get_response function fetches or generates a response
                response_data = get_response(user_id, file_name, human_input, conversation_id)
                if 'body' in response_data:
                    cleaned_response = clean_chat_response(response_data['body'])
                    assistant_response = {
                        "role": "assistant",
                        "content": f"VoiceIQ: {cleaned_response}"
                    }
                    with st.chat_message("assistant"):
                        st.markdown(assistant_response["content"])
                    st.session_state.messages.append(assistant_response)

if __name__ == "__main__":
    main()