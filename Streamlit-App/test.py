import boto3
from botocore.exceptions import NoCredentialsError
#from langchain_openai import ChatOpenAI
import os

s3=boto3.client('s3')
#open_ai_key= os.getenv('open_ai_key') 
aws_access_key_id = 'AKIASXMHSEK4BCOX3DSA'
aws_secret_access_key = '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'


# AWS S3 setup
s3 = boto3.client('s3')
BUCKET_NAME = 'audiofilellm'  
# path = '/Users/maverick1997/Downloads/01-ted-talk.mp3'

# file='01-ted-talk.mp3'
# s3_bucket_path = "audiofile/"+file

def upload_file_to_s3(file,file_name):
    s3_bucket_path = "audiofile/"+file
    response= s3.upload_file(file_name,BUCKET_NAME,s3_bucket_path)
    print(response)
        
    

file_name = 'sec.mp3'
filename = 'C:\\Users\\19452\\Downloads\\sec.mp3'
s3_path = upload_file_to_s3(file_name, filename)