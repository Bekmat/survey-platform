from flask import Flask, render_template, request, redirect, url_for, send_file, abort, flash
import uuid
import io
import pandas as pd
from datetime import datetime

app = Flask(__name__)
app.secret_key = "dev-secret-key"  # For development only; replace in production

# In-memory storage for surveys
# surveys: { survey_id: { 'title': str, 'questions': [str], 'responses': [ { 'timestamp': iso, 'answers': [str] } ] } }
surveys = {}


@app.route('/')
def index():
    # show all surveys
    items = [
        {"id": sid, "title": data["title"], "responses_count": len(data["responses"])}
        for sid, data in surveys.items()
    ]
    return render_template('index.html', surveys=items)


@app.route('/create', methods=['GET', 'POST'])
def create_survey():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        questions_raw = request.form.get('questions', '').strip()
        if not title:
            flash('Введите название опроса', 'danger')
            return redirect(url_for('create_survey'))
        # parse questions: one per line, ignore empty
        questions = [q.strip() for q in questions_raw.splitlines() if q.strip()]
        if not questions:
            flash('Добавьте хотя бы один вопрос (по одному на строку)', 'danger')
            return redirect(url_for('create_survey'))
        sid = str(uuid.uuid4())
        surveys[sid] = {
            'title': title,
            'questions': questions,
            'responses': []
        }
        flash('Опрос создан', 'success')
        return redirect(url_for('index'))
    return render_template('create.html')


@app.route('/survey/<survey_id>', methods=['GET', 'POST'])
def take_survey(survey_id):
    survey = surveys.get(survey_id)
    if survey is None:
        abort(404)
    if request.method == 'POST':
        answers = []
        for i in range(len(survey['questions'])):
            a = request.form.get(f'q{i}', '').strip()
            answers.append(a)
        response = {
            'timestamp': datetime.utcnow().isoformat(),
            'answers': answers
        }
        survey['responses'].append(response)
        flash('Спасибо! Ваши ответы сохранены.', 'success')
        return redirect(url_for('results', survey_id=survey_id))
    return render_template('survey.html', survey=survey, survey_id=survey_id)


@app.route('/results/<survey_id>')
def results(survey_id):
    survey = surveys.get(survey_id)
    if survey is None:
        abort(404)
    # Build pandas DataFrame of responses
    questions = survey['questions']
    rows = []
    for resp in survey['responses']:
        row = { 'timestamp': resp.get('timestamp') }
        for idx, q in enumerate(questions):
            # use short column names or full questions? we'll use Q1, Q2... and provide mapping
            row[f'Q{idx+1}'] = resp['answers'][idx] if idx < len(resp['answers']) else ''
        rows.append(row)
    if rows:
        df = pd.DataFrame(rows)
    else:
        # empty DataFrame with columns
        cols = ['timestamp'] + [f'Q{i+1}' for i in range(len(questions))]
        df = pd.DataFrame(columns=cols)
    # convert df to HTML table for display (bootstrap classes)
    table_html = df.to_html(classes='table table-striped', index=False, escape=True)
    # Provide a mapping of Q1.. to full question text
    q_map = { f'Q{i+1}': q for i, q in enumerate(questions) }
    return render_template('results.html', survey=survey, table_html=table_html, q_map=q_map, survey_id=survey_id)


@app.route('/download/<survey_id>')
def download_excel(survey_id):
    survey = surveys.get(survey_id)
    if survey is None:
        abort(404)
    questions = survey['questions']
    rows = []
    for resp in survey['responses']:
        row = { 'timestamp': resp.get('timestamp') }
        for idx, q in enumerate(questions):
            row[q] = resp['answers'][idx] if idx < len(resp['answers']) else ''
        rows.append(row)
    if rows:
        df = pd.DataFrame(rows)
    else:
        # empty DataFrame with question columns
        cols = ['timestamp'] + questions
        df = pd.DataFrame(columns=cols)
    # write to excel in-memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Responses')
    output.seek(0)
    filename = f"survey_{survey_id}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


if __name__ == '__main__':
    # Development server
    app.run(debug=True)
