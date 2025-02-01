import os
from flask import Flask, request

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')


@app.route('/', methods=['POST', 'GET'])
def ussd_callback():
    text = request.values.get("text", "default")
    if not text:
        response = 'CON Welcome to YoFarm Hub B2B!\n'
        response += 'Please select an option:\n\n'
        response += '1. Sell Produce\n'
        response += '2. Buy Produce\n\n'
        response += 'Enter your response: '
    elif text == '1' or text == '2':
        response = 'CON You have selected: '
        if text == '1':
            response += '1. Sell Produce'
        else:
            response += '2. buy produce'
        response += '\n\nProceeding to the next step...\n\n'
        response += 'Enter District: '
    elif text.startswith('1*') or text.startswith('2*'):
        if text[2:].endswith('*1') or text[2:].endswith('*2'):
            if text.endswith('1'):
                response = 'END Thank you for your response! We will connect with you as soon as possible.\n\n'
                response += 'Yofarm Hub - Transforming Agribusiness'
            else:
                response = 'END End'
        else:
            isalpha = False
            for ch in text[2:]:
                if not ch.isalpha:
                    break
            else:
                isalpha = True

            if isalpha:
                response = f"CON District: {text[2:]}\n\n"
                response += 'Proceeding to the next step…\n\n'
                response += 'Would you like to:\n\n'
                response += '1. Continue\n'
                response += '2. Go Back\n\n'
                response += 'Enter your response: '
            else:
                response = 'END Error: Invalid input. Please enter the district name using only alphabets.'

    else:
        response = 'END Error: Invalid input. Please enter a valid option'

    return response


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
