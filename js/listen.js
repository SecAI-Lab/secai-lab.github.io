document.addEventListener("DOMContentLoaded", function() {
    const toggles = document.querySelectorAll(".toggle-triangle");
    
    toggles.forEach(function(toggle) {
      toggle.addEventListener("click", function() {
        const dottedBox = this.parentElement.querySelector(".dotted-box");
        dottedBox.style.display = dottedBox.style.display === "none" || !dottedBox.style.display ? "block" : "none";
        this.textContent = dottedBox.style.display === "block" ? "▼" : "▶"; // Change the triangle direction
      });
    });
  });
