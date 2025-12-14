from flask import Flask, render_template, request, redirect, url_for, send_file, abort, flash
import uuid
import io
import pandas as pd
from datetime import datetime
import plotly.express as px
import plotly.io as pio
from flask_sqlalchemy import SQLAlchemy
import json

app = Flask(__name__)
app.secret_key = "dev-secret-key"  # For development only; replace in production

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///surveys.db'
db = SQLAlchemy(app)

class Survey(db.Model):
    __tablename__ = 'surveys'
    id = db.Column(db.String(36), primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    questions = db.Column(db.Text, nullable=False)  # JSON
    responses = db.Column(db.Text, default='[]')  # JSON
    is_template = db.Column(db.Boolean, default=False)

# In-memory storage for surveys
# surveys: { survey_id: { 'title': str, 'questions': [dict], 'responses': [dict], 'is_template': bool } }
surveys = {}

def save_survey(sid):
    s = surveys[sid]
    survey_db = Survey.query.get(sid)
    if not survey_db:
        survey_db = Survey(id=sid, title=s['title'], questions=json.dumps(s['questions']), responses=json.dumps(s['responses']), is_template=s['is_template'])
        db.session.add(survey_db)
    else:
        survey_db.title = s['title']
        survey_db.questions = json.dumps(s['questions'])
        survey_db.responses = json.dumps(s['responses'])
        survey_db.is_template = s['is_template']
    db.session.commit()


@app.context_processor
def inject_lists():
    # Provides templates and active surveys for templates and header dropdown
    templates_items = [
        {"id": sid, "title": data["title"], "responses_count": len(data["responses"])}
        for sid, data in surveys.items() if data.get('is_template', False)
    ]
    header_surveys = [
        {"id": sid, "title": data["title"]}
        for sid, data in surveys.items() if not data.get('is_template', False)
    ]
    return dict(templates_items=templates_items, header_surveys=header_surveys)


@app.route('/')
def index():
    # Main page: Create and templates list
    return render_template('index.html')


@app.route('/create', methods=['GET', 'POST'])
def create_survey():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        is_template = request.form.get('is_template') == 'on'  # Checkbox value
        
        if not title:
            flash('Введите название опроса', 'danger')
            return redirect(url_for('create_survey'))
        
        # Parse questions from form
        questions = []
        index = 0
        while True:
            text_key = f'questions[{index}][text]'
            type_key = f'questions[{index}][type]'
            
            text = request.form.get(text_key, '').strip()
            q_type = request.form.get(type_key, 'text')
            
            if not text:
                break  # No more questions
            
            options = []
            opt_index = 0
            while True:
                opt_key = f'questions[{index}][options][{opt_index}]'
                opt = request.form.get(opt_key, '').strip()
                if not opt:
                    break
                options.append(opt)
                opt_index += 1
            
            questions.append({
                'text': text,
                'type': q_type,
                'options': options
            })
            index += 1
        
        if not questions:
            flash('Добавьте хотя бы один вопрос', 'danger')
            return redirect(url_for('create_survey'))
        
        sid = str(uuid.uuid4())
        surveys[sid] = {
            'title': title,
            'questions': questions,
            'responses': [],
            'is_template': is_template
        }
        save_survey(sid)
        
        if is_template:
            flash('✓ Шаблон создан успешно!', 'success')
            return redirect(url_for('templates_list'))
        else:
            flash('✓ Опрос создан успешно!', 'success')
            return redirect(url_for('responses_list'))
    
    return render_template('create.html')


@app.route('/templates')
def templates_list():
    # Show only templates (is_template=True)
    items = [
        {"id": sid, "title": data["title"], "responses_count": len(data["responses"])}
        for sid, data in surveys.items() if data.get('is_template', False)
    ]
    return render_template('templates.html', items=items)


@app.route('/template/<survey_id>/use')
def use_template(survey_id):
    # Create a new ACTIVE survey from a template
    survey = surveys.get(survey_id)
    if survey is None:
        abort(404)
    
    if not survey.get('is_template', False):
        flash('Это не шаблон', 'danger')
        return redirect(url_for('templates_list'))
    
    # Create a new survey from template
    new_id = str(uuid.uuid4())
    surveys[new_id] = {
        'title': survey['title'],
        'questions': survey['questions'][:],  # copy
        'responses': [],
        'is_template': False  # New survey is NOT a template
    }
    
    flash('✓ Новый опрос создан на основе шаблона!', 'success')
    return redirect(url_for('responses_list'))


@app.route('/template/<survey_id>/delete', methods=['POST'])
def delete_template(survey_id):
    survey = surveys.get(survey_id)
    if survey and survey.get('is_template', False):
        del surveys[survey_id]
        survey_db = Survey.query.get(survey_id)
        if survey_db:
            db.session.delete(survey_db)
            db.session.commit()
        flash('✓ Шаблон удалён!', 'success')
    else:
        flash('Это не шаблон', 'danger')
    return redirect(url_for('templates_list'))


@app.route('/responses')
def responses_list():
    # List all ACTIVE surveys (is_template=False)
    items = [
        {"id": sid, "title": data["title"], "responses_count": len(data["responses"])}
        for sid, data in surveys.items() if not data.get('is_template', False)
    ]
    return render_template('responses_list.html', items=items)


@app.route('/survey/<survey_id>', methods=['GET', 'POST'])
def take_survey(survey_id):
    survey = surveys.get(survey_id)
    if survey is None:
        abort(404)
    
    if survey.get('is_template', False):
        flash('Нельзя проходить опрос-шаблон. Используйте его копию.', 'warning')
        return redirect(url_for('templates_list'))
    
    if request.method == 'POST':
        flash(f"Form data: {dict(request.form)}", 'info')
        answers = []
        for i, q in enumerate(survey['questions']):
            if q['type'] == 'checkbox':
                ans = request.form.getlist(f'q{i}')
                answers.append(ans)  # list
            else:
                ans = request.form.get(f'q{i}', '').strip()
                answers.append(ans)  # str
        flash(f"Parsed answers: {answers}", 'info')
        response = {
            'timestamp': datetime.utcnow().isoformat(),
            'answers': answers
        }
        survey['responses'].append(response)
        save_survey(survey_id)
        flash('✓ Спасибо! Ваши ответы сохранены.', 'success')
        return redirect(url_for('responses_list'))
    return render_template('survey.html', survey=survey, survey_id=survey_id)


@app.route('/survey/<survey_id>/responses/view')
def view_survey_responses(survey_id):
    survey = surveys.get(survey_id)
    if survey is None:
        abort(404)
    
    if survey.get('is_template', False):
        flash('Это шаблон. Результаты будут доступны после использования.', 'info')
        return redirect(url_for('templates_list'))
    
    # Build pandas DataFrame of responses
    questions = survey['questions']
    rows = []
    for resp in survey['responses']:
        row = { 'timestamp': resp.get('timestamp') }
        for idx, q in enumerate(questions):
            ans = resp['answers'][idx] if idx < len(resp['answers']) else []
            if q['type'] == 'checkbox':
                if isinstance(ans, list):
                    for opt in q['options']:
                        row[f'Q{idx+1}_{opt}'] = 'Да' if opt in ans else 'Нет'
                else:
                    for opt in q['options']:
                        row[f'Q{idx+1}_{opt}'] = 'Нет'
            else:
                if isinstance(ans, list):
                    row[f'Q{idx+1}'] = ', '.join(ans)
                else:
                    row[f'Q{idx+1}'] = ans
        rows.append(row)
    if rows:
        df = pd.DataFrame(rows)
    else:
        # Build columns
        cols = ['timestamp']
        for idx, q in enumerate(questions):
            if q['type'] == 'checkbox':
                for opt in q['options']:
                    cols.append(f'Q{idx+1}_{opt}')
            else:
                cols.append(f'Q{idx+1}')
        df = pd.DataFrame(columns=cols)
    table_html = df.to_html(classes='table table-striped table-bordered', index=False, escape=True, table_id='resultsTable')
    q_map = {}
    for idx, q in enumerate(questions):
        if q['type'] == 'checkbox':
            for opt in q['options']:
                q_map[f'Q{idx+1}_{opt}'] = f"{q['text']} - {opt}"
        else:
            q_map[f'Q{idx+1}'] = q['text']
    return render_template('view_responses.html', survey=survey, table_html=table_html, q_map=q_map, survey_id=survey_id)


@app.route('/survey/<survey_id>/delete', methods=['POST'])
def delete_survey(survey_id):
    survey = surveys.get(survey_id)
    if survey and not survey.get('is_template', False):
        del surveys[survey_id]
        survey_db = Survey.query.get(survey_id)
        if survey_db:
            db.session.delete(survey_db)
            db.session.commit()
        flash('✓ Опрос удалён!', 'success')
    else:
        flash('Это шаблон. Используйте "Удалить" в разделе Шаблонов.', 'warning')
    return redirect(url_for('responses_list'))


@app.route('/survey/<survey_id>/results')
def survey_results(survey_id):
    survey = surveys.get(survey_id)
    if survey is None:
        abort(404)
    
    if survey.get('is_template', False):
        flash('Это шаблон. Результаты будут доступны после использования.', 'info')
        return redirect(url_for('templates_list'))
    
    questions = survey['questions']
    responses = survey['responses']
    
    charts = []
    for idx, q in enumerate(questions):
        if q['type'] in ['radio', 'checkbox']:
            # Collect all answers for this question
            answers = []
            for resp in responses:
                ans = resp['answers'][idx] if idx < len(resp['answers']) else []
                if isinstance(ans, list):
                    answers.extend(ans)
                else:
                    if ans:
                        answers.append(ans)
            
            if answers:
                # Count frequencies
                freq = pd.Series(answers).value_counts()
                fig = px.bar(freq, x=freq.index, y=freq.values, title=q['text'], labels={'x': 'Ответ', 'y': 'Количество'})
                chart_html = pio.to_html(fig, full_html=False)
                charts.append(chart_html)
        elif q['type'] == 'text':
            # For text, maybe word cloud or just list, but for now skip or show frequency of common words
            answers = [resp['answers'][idx] for resp in responses if idx < len(resp['answers']) and resp['answers'][idx]]
            if answers:
                # Simple bar chart of most common responses
                freq = pd.Series(answers).value_counts().head(10)
                fig = px.bar(freq, x=freq.index, y=freq.values, title=q['text'], labels={'x': 'Ответ', 'y': 'Количество'})
                chart_html = pio.to_html(fig, full_html=False)
                charts.append(chart_html)
    
    return render_template('results.html', survey=survey, charts=charts, survey_id=survey_id)


@app.route('/survey/<survey_id>/download')
def download_excel(survey_id):
    survey = surveys.get(survey_id)
    if survey is None:
        abort(404)
    
    if survey.get('is_template', False):
        flash('Нельзя скачать результаты шаблона', 'warning')
        return redirect(url_for('templates_list'))
    
    questions = survey['questions']
    rows = []
    for resp in survey['responses']:
        row = { 'timestamp': resp.get('timestamp') }
        for idx, q in enumerate(questions):
            ans = resp['answers'][idx] if idx < len(resp['answers']) else []
            if q['type'] == 'checkbox':
                if isinstance(ans, list):
                    for opt in q['options']:
                        row[f"{q['text']} - {opt}"] = 'Да' if opt in ans else 'Нет'
                else:
                    for opt in q['options']:
                        row[f"{q['text']} - {opt}"] = 'Нет'
            else:
                if isinstance(ans, list):
                    row[q['text']] = ', '.join(ans)
                else:
                    row[q['text']] = ans
        rows.append(row)
    if rows:
        df = pd.DataFrame(rows)
    else:
        # Build columns
        cols = ['timestamp']
        for q in questions:
            if q['type'] == 'checkbox':
                for opt in q['options']:
                    cols.append(f"{q['text']} - {opt}")
            else:
                cols.append(q['text'])
        df = pd.DataFrame(columns=cols)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Responses')
    output.seek(0)
    filename = f"survey_{survey_id}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


if __name__ == '__main__':
    # Development server
    with app.app_context():
        db.create_all()
        # Load surveys into memory
        for s in Survey.query.all():
            surveys[s.id] = {
                'title': s.title,
                'questions': json.loads(s.questions),
                'responses': json.loads(s.responses),
                'is_template': s.is_template
            }
    app.run(debug=True)
