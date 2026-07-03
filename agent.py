from langgraph.graph import StateGraph,START,END
from typing import TypedDict, Optional
from langchain_ollama import ChatOllama
from chroma_l import db
from datetime import date
from langchain_core.documents import Document
from auth import service
from langgraph.prebuilt import create_react_agent
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
import base64
from email.mime.text import MIMEText
import gradio as gr
from pprint import pprint
import os
from dotenv import load_dotenv
from messaging import send_gmail_task

ollama = ChatOllama(
    model="llama3:latest",  
    temperature=0
)
load_dotenv()
api_key=os.getenv("API_KEY")

model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
   
    google_api_key="AIzaSyCn0_yuqCEqGSJlufmppoqJ5-hFQCYQfuE"
)








class State(TypedDict):
  promt:str
  next:str
  report:str
  sender:str
  messages:list
def init(state:State):
  

  db.delete(
  
    where={
        "$and": [
            {"type": "tasks"},
            {"date": {"$ne": "2026-07-03"}}
        ]
    }

)
  
  with open("tasks.txt","r",encoding="utf-8") as file:
    data=file.read()
  if data!="":
    db.add_documents([Document(page_content=data,  metadata={
        "type": "tasks",
        "date": str(date.today())
    })])

  query=state["promt"]
  with open("basic_pr.txt","r",encoding="utf-8") as f:
    PROMPT=f.read()
  final=f"{PROMPT}\n\n{query}"
  res=ollama.invoke(final)
  
 
  state["next"]=res.content.strip("**").strip("**")
  print(state["next"])
  return  state
def summary_top(state:State):
  res=ollama.invoke(f"You are an email extractor agent. Extract the sender's email address from the user's query. Respond with only the exact email address. If no email address is present, respond with `out`. Do not provide any explanation or additional text.\n {state['promt']}")
  gmail=res.content
  state["sender"]=gmail
  results = service.users().messages().list(
        userId="me",
        q=f"from:{gmail}",
        maxResults=5
    ).execute()
  messages=results.get("messages",[])
  email=[]
  for msg in messages:
      msg_data = service.users().messages().get(
            userId="me",
            id=msg["id"]
        ).execute()
      subject=None
      headers = msg_data["payload"]["headers"]
      for head in headers:
        if head["name"]=="Subject":
          subject=head["value"]
      email.append({"subject":subject,"body":msg_data.get("snippet","")})
      service.users().messages().modify(
        userId="me",
        id=msg["id"],
        body={"removeLabelIds": ["UNREAD"]}
    ).execute()
  emails="\n\n".join(f"subject:{msg['subject']}\nbody:{msg['body']}\n\n" for msg in email)
  promt=f"""
  you are a summarization agent summarize the below mails a/c to subject and body the mails are from
  sender:
  {gmail}
  content:
  {emails}
  """
  res1=ollama.invoke(promt)
  state["report"]=res1.content
  state["messages"]=state["messages"]+[{"human":state["promt"],"ai":res1.content}]
  db.add_documents([Document(page_content=res1.content,metadata={f"from":f"{gmail}"})])
  return state
def chat_bot(state:State):
    retriever = db.as_retriever(
        search_kwargs={"k": 10}
    )
    docs = retriever.invoke(state["promt"])
    content="\n\n".join(doc.page_content for doc in docs)
    history = "\n\n".join(
    f"Human: {chat['human']}\nAssistant: {chat['ai']}"
    for chat in state["messages"]
)

    prompt = f"""
You are an AI assistant.

Use the following context to answer the user's question only answer a/c to the context u have .

Context:
{content}

Question:
{state["promt"]}

history:
{history}

""" 
    res_chat=ollama.invoke(prompt)
    state["report"]=res_chat.content
    state["messages"].append({"human":state["promt"],"ai":res_chat.content})
    return state
def unread_summary(state:State):
  results = service.users().messages().list(
    userId="me",
    q="is:unread",
    maxResults=10
).execute()

  messages = results.get("messages", [])
  
  email=[]
  for msg in messages:
    msg_data = service.users().messages().get(
            userId="me",
            id=msg["id"]
        ).execute()
    subject=None
    sender=None
    headers = msg_data["payload"]["headers"]
    for head in headers:
        if head["name"]=="Subject":
          subject=head["value"]
        elif head["name"]=="From":
           sender=head["value"]
    service.users().messages().modify(
        userId="me",
        id=msg["id"],
        body={"removeLabelIds": ["UNREAD"]}
    ).execute()
    email.append({"subject":subject,"sender":sender,"body":msg_data.get("snippet","")})
  
  emails="\n\n".join(f"from:{msg['sender']}\nsubject:{msg['subject']}\nbody:{msg['body']}\n\n" for msg in email)
  
  promt=f"""
  you are a summarization agent summarize the below mails a/c to subject and body and sender just only summarize dont add any extra text
  
  content:
  {emails}
  """
  res=ollama.invoke(promt)
  db.add_documents([Document(page_content=emails,metadata={"type":"random mail summarization"})])
  state["report"]=res.content
  state["messages"].append({"human":state["promt"],"ai":res.content})
  return state
async def automation(state:State):
  client=MultiServerMCPClient({"remote-server":{
      "url":"http://127.0.0.1:8001/sse",
      "transport": "sse"
    }})
  tools=await client.get_tools()
  prompt=f"""
      You are a Gmail Automation Agent.

You have access to Gmail automation tools. Analyze the user's request, select the appropriate tool(s), and execute them when required.

Rules:
-if you want to reply to any gmail use the retriever tool before you use reply tool try to create a query that includes sender gmail and relative content in body it will be easy for retrival
-also you will be having user past conversation history
- Always use the most appropriate tool to fulfill the user's request.
- Do not describe which tool you used.
- After completing the action, respond with a single concise sentence confirming the result a/c to result from tool.
-if u find any gmail is needed to be summarised just summarise and and the return the summarised data
-just do use requried tools and complete the task dont ask me do i need to summarise or put it in spam like that
- If the requested action cannot be completed, explain the reason in one concise sentence.
- Do not provide unnecessary explanations or reasoning.

  """
  agent=create_agent(model=model,tools=tools,system_prompt=prompt)
  results = service.users().messages().list(
    userId="me",
    q="is:unread",
    maxResults=10
).execute()

  messages = results.get("messages", [])
  email=[]
  for msg in messages:
    msg_data = service.users().messages().get(
            userId="me",
            id=msg["id"]
        ).execute()
    subject=None
    sender=None
    headers = msg_data["payload"]["headers"]
    for head in headers:
        if head["name"]=="Subject":
          subject=head["value"]
        elif head["name"]=="From":
           sender=head["value"]
    service.users().messages().modify(
        userId="me",
        id=msg["id"],
        body={"removeLabelIds": ["UNREAD"]}
    ).execute()
    email.append({"subject":subject,"sender":sender,"body":msg_data.get("snippet",""),"thread_id": msg_data["threadId"]})
  sum=""
  track=""
  for e in email:
     data=f"from:\n{e['sender']}\nsubject:{e['subject']}\nbody:{e['body']}\nthread_id:{e['thread_id']}\n\nhistory:{state['messages']}"
     res=None
     try:
        res=await agent.ainvoke({"messages":[{"role":"user","content": data}]})
     except Exception as e:
      print(f"Automation error: {e}")
      state["report"] = f"Error occurred while automating: {e}"
      return state
        
     print(data)
     
     last_msg = res["messages"][-1].content

     if isinstance(last_msg, list):
          text_parts = []

          for part in last_msg:
              if isinstance(part, dict):
                  if "text" in part and isinstance(part["text"], str):
                      text_parts.append(part["text"])
                  elif "content" in part and isinstance(part["content"], str):
                      text_parts.append(part["content"])

          auto = " ".join(text_parts).strip()

     else:
          auto = str(last_msg).strip()
     state["messages"].append({"human":"automate gmail","ai":auto})
     sum=sum+"\n\n"+auto
     track=track+"\n\n"+data+"\n\n"+auto+"\n\n"
  db.add_documents([Document(page_content=track,metadata={"type":"automated"})])
  state["report"]=sum
  return state
def send(state:State):
   res=ollama.invoke(f"You are an email extractor agent. Extract the sender's email address from the user's query. Respond with only the exact email address. If no email address is present, respond with `out`. Do not provide any explanation or additional text.\n {state['promt']}")
   print(res.content)
   gmail=res.content
   state["sender"]=gmail
   gmail=state["sender"]
   query=state["promt"]
   retriver=db.as_retriever()
   q=f"{date.today} tasks\n{gmail}\n{query}"
   context=retriver.invoke(q)
   content="\n\n".join(doc.page_content for doc in context)
   print(content)
   prompt = f"""
You are an AI Gmail email body generation agent.

Your task is to generate only the body of an email based on the user's request.

Instructions:
-DONT RETURN THIS KIND OF LINES
*** 
Please note that I have ignored the provided context as it seems unrelated to the user's request. The tone is professional and congratulatory, suitable for acknowledging someone's achievement.
***
-DONT RETURN THIS KIND OF LINES
***
Based on the user's request, I will generate an email body that congratulates Jaswanthcyber@gmail.com on getting the highest package.
***
- Use the provided context only if it is relevant to the user's request.
-**IF THE PROVIDED CONTEXT IN UNRELATED SKIP THAT**"
- If the context is unrelated or insufficient, ignore it and generate the email body based solely on the user's request.
- Do not generate a subject line, recipient, greeting metadata, or explanations.
- Return only the email body as plain text.
- Keep the tone appropriate to the user's request (e.g., professional, friendly, formal, or casual).
-**RETURN ONLY THE EMAIL BODY AS PLAIN TEXT NOTHING ELSE**

User Request:
{query}

Retrieved Context:
{content}
"""
   res=ollama.invoke(prompt)
   body=res.content
   res1=ollama.invoke(f"generate the subject for the gmail only subject in text format dont generate anything other\n gmail:\n{body}")
   subject=res1.content
   send_gmail_task.delay(gmail,body,subject)
   state["messages"].append({"user":state['promt'],"ai":f"subject:\n{subject}\n\nbody:{body}"})
   db.add_documents([Document(page_content=f"{state['promt']}\n\nsubject:{subject}\n\nbody:{body}",metadata={f"to":gmail})])
   state["report"]=f"sent gmail sucessfully to{gmail}\n\nbody:\n{body}\n\nsubject:\n{subject}"
   return state
def final(state:State):
   if not state["report"]:
      state["report"]="Enter the correct prompt or enter correct gmail adress"
      return state
   print(state["report"])
   res = ollama.invoke(
        f"""
        
Format the following content as clean Markdown for display in a Gradio Markdown component.

Content:

{state['report']}
"""
    )
   state['report']=res.content
   return state
work=StateGraph(State)
work.add_node("init",init)
work.add_node("summary_top",summary_top)
work.add_node("chat_bot",chat_bot)
work.add_node("unread_summary",unread_summary)
work.add_node("automation",automation)
work.add_node("send",send)
work.add_node("out",final)
work.set_entry_point("init")
work.add_conditional_edges(
  "init",
  lambda s:s["next"],
  {
    "s1":"unread_summary",
    "s2":"summary_top",
    "G1":"send",
    "a1":"automation",
    "c1":"chat_bot",
    "out":"out"

  }

)
work.add_edge("summary_top","out")
work.add_edge("unread_summary","out")
work.add_edge("send","out")
work.add_edge("automation","out")
work.add_edge("chat_bot","out")
work.add_edge("out",END)
graph=work.compile()
async def invoke(message, history):
    messages = []

    human = None

    for chat in history:
        if chat["role"] == "user":
            human = chat["content"][0]["text"]

        elif chat["role"] == "assistant":
            ai = chat["content"][0]["text"]

            messages.append({
                "human": human,
                "ai": ai
            })

    result = await graph.ainvoke({
        "promt": message,
        "next": "",
        "report": "",
        "sender": "",
        "messages": messages
    })

    return result["report"]
def inter():
   with gr.Blocks(
    css="""
    .gradio-container {
        max-width: 900px !important;
        margin: auto !important;
    }
    """
) as demo:

    gr.ChatInterface(
        fn=invoke,
        title="📧 Gmail Assistant",
        description="Let's go..."
    )

   demo.launch()
if __name__=="__main__":
   inter()










  


  
     

   
    

    




  
