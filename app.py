from flask import Flask, request, render_template

app = Flask(__name__)

DROPBOX_EXE_URL = "https://drive.google.com/file/d/15FZUPc12eopGoXOGxHsj2cYOx8Nn7bzE/view?usp=drive_link"

@app.route("/candidate")
def candidate_page():
    email = request.args.get("email")
    interview_time = request.args.get("time")  # format: YYYY-MM-DD_HH_MM_SS
    return render_template("candidate.html", email=email, interview_time=interview_time, exe_link=DROPBOX_EXE_URL)

if __name__ == "__main__":
    app.run(debug=True)
