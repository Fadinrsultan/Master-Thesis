// Called when “Search” button is clicked
async function sendSearch() {
  const query = document.getElementById("searchBox").value;
  try {
    const response = await fetch("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query })
    });
    const data = await response.json();
    document.getElementById("result").innerText = data.response;
  } catch (err) {
    document.getElementById("result").innerText = `Error: ${err.message}`;
  }
}

// Clears the input box and result text
function clearInput() {
  document.getElementById("searchBox").value = "";
  document.getElementById("result").innerText = "";
}

// Shows/hides the chat window
function toggleChat() {
  const chatWindow = document.getElementById("chatWindow");
  chatWindow.style.display =
    chatWindow.style.display === "none" ? "flex" : "none";
}

// Called when user presses “Enter” or clicks the chat send button
async function sendChat() {
  const inputField = document.getElementById("chatField");
  const message = inputField.value;
  if (!message) return;

  // Display “You:” in the chat window
  const chatMessagesDiv = document.getElementById("chatMessages");
  chatMessagesDiv.innerHTML += "<b>You:</b> " + message + "<br>";
  inputField.value = "";

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message })
    });
    const data = await response.json();
    chatMessagesDiv.innerHTML += "<b>GPT:</b> " + data.response + "<br><br>";
    chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
  } catch (err) {
    chatMessagesDiv.innerHTML += `<b>Error:</b> ${err.message}<br><br>`;
    chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
  }
}
