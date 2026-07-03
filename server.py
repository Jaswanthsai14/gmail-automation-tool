from fastmcp import FastMCP
from auth import service
from chroma_l import db
import base64
from email.mime.text import MIMEText
from langchain_ollama import ChatOllama
from messaging import reply_gmail_task
ollama = ChatOllama(
    model="llama3:latest",  
    temperature=0
)
mcp=FastMCP("remote7")
@mcp.tool()
def retriever(query: str)->str:
    """
Search previously stored Gmail summaries and email content.

Use this tool before replying to an email if you need to retrieve
the sender, subject, thread ID, or original email body.
"""

    docs = db.as_retriever().invoke(query)

    return "\n\n".join(
        d.page_content
        for d in docs
    )
@mcp.tool()
def reply_gmail(sender:str,reply_text:str,subject:str,thread_id:str)->str:
    """
    Reply to an existing Gmail conversation.

    Args:
        sender: Recipient's email address.
        subject: Original email subject.
        reply_text: The reply message to send.
        thread_id: Gmail thread ID of the conversation.

    Returns:
        A confirmation message if the reply is sent successfully.
    
    """
    return reply_gmail_task.delay(sender,reply_text,subject,thread_id)
@mcp.tool()
def spam(sender:str,body:str)->str:
    """this tool stores the spam gmails in the spam folder
      Args:
        -body->string
      """
    with open("spam.txt", "a", encoding="utf-8") as file:
      file.write(
        f"\nSender: {sender}\n"
        f"Body:\n{body}\n"
        "----------------------\n"
    )
    return "stored in spam folder"
@mcp.tool()
def summarize(body:str)->str:
     """this tool summarizes the gmails
      Args:
        -body->string
      """
     prompt=f"summarize the following message\n{body}"
     res=ollama.invoke(prompt)
     return res.content
if __name__ == "__main__":
    
   
    print("Starting MCP server...")
    mcp.run(transport="sse", port=8001)

     

