"""Create the first administrator interactively without putting passwords in shell history."""
import getpass, os
from app import app, db, User, Video

def main():
    with app.app_context():
        username = input('Admin username (3+ chars): ').strip()
        if len(username) < 3:
            raise SystemExit('Username must be at least 3 characters.')
        if User.query.filter_by(username=username).first():
            raise SystemExit('That username already exists.')
        password = getpass.getpass('Admin password (12+ chars): ')
        confirm = getpass.getpass('Confirm password: ')
        if len(password) < 12 or password != confirm:
            raise SystemExit('Passwords must match and be at least 12 characters.')
        user = User(username=username, role='admin', enabled=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        Video.query.filter(Video.user_id.is_(None)).update({Video.user_id: user.id}, synchronize_session=False)
        db.session.commit()
        print(f'Administrator {username!r} created. Keep the password private.')
if __name__ == '__main__':
    main()
