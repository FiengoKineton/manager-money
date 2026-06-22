(function () {
  function updateAvatarFilename() {
    var input = document.getElementById("avatar");
    if (!input) return;

    input.addEventListener("change", function () {
      var fileName = input.files && input.files.length ? input.files[0].name : "";
      var drop = document.querySelector(".avatar-drop strong");
      if (drop && fileName) drop.textContent = fileName;
    });
  }

  document.addEventListener("DOMContentLoaded", updateAvatarFilename);
})();
