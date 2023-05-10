# -*- coding: utf-8 -*-

import os
import yaml
import json
from deepmerge import always_merger

import base64
from cryptography.fernet import Fernet
from hashlib import sha256

import redis

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_bootstrap import Bootstrap5, SwitchField
from flask_wtf import FlaskForm, CSRFProtect
from wtforms.validators import DataRequired, Length, Regexp
from wtforms.fields import *
import secrets
import datetime

app = Flask(__name__)

# config for application {{
baseCfg = {
    'redis': {
        'host': 'redis',
        'port': 6379
    },
    'salt': 'CHANGE_ME',
    'urlRoot': False,
    'defaultExpiredDays': 1,
}
configFile = os.environ.get('CONFIG_FILE', False)
if configFile:
    if os.path.isfile(configFile):
        try:
            with open(configFile, 'r') as ymlfile:
                yamlCfg = yaml.load(ymlfile,Loader=yaml.Loader)
        except Exception as e:
            app.logger.error('failed load config file: "%s", error: "%s"' % (configFile, e))
            exit(1)
        cfg = always_merger.merge(baseCfg,yamlCfg)
    else:
        cfg = baseCfg
else:
    cfg = baseCfg
app.logger.debug("cfg='%s'" % json.dumps(cfg,indent=4))
# }}

app.secret_key = secrets.token_urlsafe(16)
bootstrap = Bootstrap5(app)
csrf = CSRFProtect(app)

redisClient = redis.Redis(host=cfg['redis']['host'], port=cfg['redis']['port'])

@app.errorhandler(404)
def page_not_found(e):
    flash('Page not found!', 'warning')
    return render_template('error.html', errorCode='404', error='404'), 404

def get_default_datetime():
    return datetime.datetime.now() + datetime.timedelta(days=cfg['defaultExpiredDays'])

class SecretForm(FlaskForm):
    secret = TextAreaField('Please insert secret:', validators=[DataRequired(), Length(1, 99999)])
    expiryDatetime = DateTimeLocalField('Expiry date (UTC):', default=get_default_datetime)
    submit = SubmitField()

@app.route('/')
def index():
    return render_template('index.html', form=SecretForm())

@app.route('/result',methods = ['POST'])
def result():
    if request.method == 'POST':
        result = request.form
        secret = False
        for key,value in result.items():
            if key == 'secret':
                secret = value
            if key == 'expiryDatetime':
                expiryDatetime = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
        if secret:
            encryptKey = Fernet.generate_key()
            encryptKeySha256 = sha256(str(cfg['salt']).encode('utf-8') + str(encryptKey).encode('utf-8')).hexdigest()
            # encrypt {{
            encryptedSecret = Fernet(encryptKey).encrypt(secret.encode('utf-8'))
            # }}

            # save to redis {{
            expireSeconds = int((expiryDatetime - datetime.datetime.now()).total_seconds())
            app.logger.debug("expireSeconds='%s'" % expireSeconds)
            redisClient.set(encryptKeySha256,encryptedSecret,ex=expireSeconds)
            # }}

            encryptKeyString = encryptKey.decode('utf-8')

        if cfg['urlRoot']:
            result_url_root = cfg['urlRoot']
        else:
            result_url_root = request.url_root
        return render_template("resultUrl.html", result = result_url_root+'get/'+encryptKeyString)

@app.route('/get/<encryptKeyString>')
def get(encryptKeyString):
    try:
        encryptKey = encryptKeyString.encode('utf-8')
        encryptKeySha256 = sha256(str(cfg['salt']).encode('utf-8') + str(encryptKey).encode('utf-8')).hexdigest()
    except:
        flash('wrong url format, please check link', 'danger')
        return render_template('error.html', errorCode='400', error='400'), 400
    try:
        encryptedSecret = redisClient.get(encryptKeySha256)
        decryptedSecret = Fernet(encryptKey).decrypt(encryptedSecret).decode('utf-8')
    except:
        flash('secret not found: it has been downloaded or expired', 'danger')
        return render_template('error.html', errorCode='404', error='404'), 404

    redisClient.delete(encryptKeySha256)
    return render_template("resultSecret.html", result = decryptedSecret)

if __name__ == '__main__':
    app.run(debug = True)

