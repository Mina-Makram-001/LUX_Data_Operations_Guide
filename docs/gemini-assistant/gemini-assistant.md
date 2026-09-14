# Gemini AI Assistant

Ask any question about the documentation or system logic below.

<div style="max-width: 650px; margin: 20px auto; font-family: sans-serif;">
  <div id="chat-box" style="border: 1px solid #ccc; border-radius: 8px; padding: 15px; height: 350px; overflow-y: auto; background: #fafafa; display: flex; flex-direction: column; gap: 10px;">
    <div style="background: #e3f2fd; color: #0d47a1; padding: 10px; border-radius: 6px; align-self: flex-start;">
      Hello! How can I help you with the LUX Data Operations Guide today?
    </div>
  </div>

  <div style="margin-top: 10px; display: flex; gap: 10px;">
    <input type="text" id="user-input" placeholder="Type your question..." style="flex: 1; padding: 10px; border: 1px solid #ccc; border-radius: 4px;" onkeydown="if(event.key === 'Enter') sendMessage()"/>
    <button onclick="sendMessage()" style="padding: 10px 20px; background: #1976d2; color: white; border: none; border-radius: 4px; cursor: pointer;">Send</button>
  </div>
</div>

<script>
async function sendMessage() {
  const inputEl = document.getElementById('user-input');
  const chatBox = document.getElementById('chat-box');
  const userText = inputEl.value.trim();

  if (!userText) return;

  // Render User Message
  const userMsg = document.createElement('div');
  userMsg.style.cssText = "background: #e0e0e0; color: #333; padding: 10px; border-radius: 6px; align-self: flex-end;";
  userMsg.innerText = userText;
  chatBox.appendChild(userMsg);
  
  inputEl.value = '';
  chatBox.scrollTop = chatBox.scrollHeight;

  // Placeholder Bot Message
  const botMsg = document.createElement('div');
  botMsg.style.cssText = "background: #e3f2fd; color: #0d47a1; padding: 10px; border-radius: 6px; align-self: flex-start;";
  botMsg.innerText = "Thinking...";
  chatBox.appendChild(botMsg);
  chatBox.scrollTop = chatBox.scrollHeight;

  try {
    const response = await fetch('http://127.0.0.1:8001/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: userText })
    });

    const data = await response.json();
    if (response.ok) {
      botMsg.innerText = data.reply;
    } else {
      botMsg.innerText = "Error: " + (data.detail || "Unable to process request.");
    }
  } catch (err) {
    botMsg.innerText = "Error connecting to backend server. Make sure server.py is running on port 8001.";
  }
  
  chatBox.scrollTop = chatBox.scrollHeight;
}
</script>