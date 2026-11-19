import sys
from decimal import Decimal, InvalidOperation
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QGridLayout, QLabel, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QKeyEvent

STYLESHEET = """
QMainWindow {
    background-color: #121212;
}
QLabel#historyLabel {
    color: #888888;
    font-size: 18px;
    font-family: 'Segoe UI', Arial, sans-serif;
    padding: 5px;
}
QLabel#displayLabel {
    color: #ffffff;
    font-size: 52px;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-weight: 300;
    padding: 10px;
    border: none;
}
QPushButton {
    border-radius: 20px;
    font-size: 24px;
    font-family: 'Segoe UI', Arial, sans-serif;
    margin: 3px;
}
QPushButton:hover {
    background-color: #333333;
}
QPushButton:pressed {
    background-color: #555555;
}

/* Number Buttons - Deep dark background with pastel text */
QPushButton[cssClass="numberButton"] {
    background-color: #1a1e23; 
    color: #c4d8e2; /* Soft pastel blueish-grey */
    border: 1px solid #23282e;
}
QPushButton[cssClass="numberButton"]:hover {
    background-color: #23282e;
}
QPushButton[cssClass="numberButton"]:pressed {
    background-color: #2a3036;
}

/* Operator Buttons - Vibrant Accent */
QPushButton[cssClass="operatorButton"] {
    background-color: #ff9f0a;
    color: #ffffff;
    font-weight: bold;
    border: none;
}
QPushButton[cssClass="operatorButton"]:hover {
    background-color: #ffb340;
}
QPushButton[cssClass="operatorButton"]:pressed {
    background-color: #e58f09;
}

/* Action Buttons (C, AC, %) */
QPushButton[cssClass="actionButton"] {
    background-color: #a5a5a5;
    color: #000000;
    border: none;
}
QPushButton[cssClass="actionButton"]:hover {
    background-color: #d4d4d2;
}
QPushButton[cssClass="actionButton"]:pressed {
    background-color: #8c8c8c;
}
"""

class Calculator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Calculator")
        # Apple-like proportions
        self.setFixedSize(360, 600)
        self.setStyleSheet(STYLESHEET)
        
        # State variables
        self.current_input = "0"
        self.history = ""
        self.previous_value = None
        self.pending_operator = None
        self.new_input_expected = False
        
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Display area
        self.history_label = QLabel("")
        self.history_label.setObjectName("historyLabel")
        self.history_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        
        self.display_label = QLabel("0")
        self.display_label.setObjectName("displayLabel")
        self.display_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        display_layout = QVBoxLayout()
        display_layout.addWidget(self.history_label)
        display_layout.addWidget(self.display_label)
        display_layout.setStretch(0, 1)
        display_layout.setStretch(1, 4)
        
        main_layout.addLayout(display_layout)
        main_layout.addSpacing(20)
        
        # Buttons layout
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)
        
        buttons = [
            ('AC', 0, 0, 'actionButton'), ('C', 0, 1, 'actionButton'), ('%', 0, 2, 'actionButton'), ('/', 0, 3, 'operatorButton'),
            ('7', 1, 0, 'numberButton'), ('8', 1, 1, 'numberButton'), ('9', 1, 2, 'numberButton'), ('*', 1, 3, 'operatorButton'),
            ('4', 2, 0, 'numberButton'), ('5', 2, 1, 'numberButton'), ('6', 2, 2, 'numberButton'), ('-', 2, 3, 'operatorButton'),
            ('1', 3, 0, 'numberButton'), ('2', 3, 1, 'numberButton'), ('3', 3, 2, 'numberButton'), ('+', 3, 3, 'operatorButton'),
            ('+/-', 4, 0, 'numberButton'), ('0', 4, 1, 'numberButton'), ('.', 4, 2, 'numberButton'), ('=', 4, 3, 'operatorButton')
        ]
        
        for text, row, col, cssClass in buttons:
            btn = QPushButton(text)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            btn.setProperty("cssClass", cssClass)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda checked, t=text: self.on_button_click(t))
            grid_layout.addWidget(btn, row, col)
            
        main_layout.addLayout(grid_layout)
        main_layout.setStretchFactor(grid_layout, 1)
        central_widget.setLayout(main_layout)

    def on_button_click(self, text):
        if text.isdigit():
            self.input_number(text)
        elif text == '.':
            self.input_decimal()
        elif text in ['+', '-', '*', '/']:
            self.input_operator(text)
        elif text == '=':
            self.calculate()
        elif text == 'AC':
            self.clear_all()
        elif text == 'C':
            self.clear_current()
        elif text == '%':
            self.calculate_percentage()
        elif text == '+/-':
            self.toggle_sign()
            
    def update_display(self):
        self.display_label.setText(self.current_input)
        self.history_label.setText(self.history)

    def format_decimal(self, dec: Decimal):
        s = f"{dec:f}"
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
        if not s:
            s = "0"
        return s

    def input_number(self, num_str):
        if self.new_input_expected:
            self.current_input = num_str
            self.new_input_expected = False
        else:
            if self.current_input == "0":
                self.current_input = num_str
            else:
                self.current_input += num_str
        self.update_display()

    def input_decimal(self):
        if self.new_input_expected:
            self.current_input = "0."
            self.new_input_expected = False
        elif '.' not in self.current_input:
            self.current_input += "."
        self.update_display()

    def input_operator(self, op):
        if self.previous_value is not None and not self.new_input_expected:
            self.calculate(internal=True)
            
        self.previous_value = Decimal(self.current_input)
        self.pending_operator = op
        
        sign = "\u00d7" if op == "*" else "\u00f7" if op == "/" else op
        self.history = f"{self.format_decimal(self.previous_value)} {sign}"
        self.new_input_expected = True
        self.update_display()

    def calculate(self, internal=False):
        if self.pending_operator is None or self.previous_value is None:
            return
            
        current_val = Decimal(self.current_input)
        result = Decimal('0')
        
        try:
            if self.pending_operator == '+':
                result = self.previous_value + current_val
            elif self.pending_operator == '-':
                result = self.previous_value - current_val
            elif self.pending_operator == '*':
                result = self.previous_value * current_val
            elif self.pending_operator == '/':
                if current_val == 0:
                    self.current_input = "Error"
                    self.new_input_expected = True
                    self.pending_operator = None
                    self.history = ""
                    self.update_display()
                    return
                result = self.previous_value / current_val
                
            self.current_input = self.format_decimal(result)
            
            if not internal:
                op_sign = "\u00d7" if self.pending_operator == "*" else "\u00f7" if self.pending_operator == "/" else self.pending_operator
                self.history = f"{self.format_decimal(self.previous_value)} {op_sign} {self.format_decimal(current_val)} ="
                self.pending_operator = None
                self.previous_value = None
            else:
                self.previous_value = result

            self.new_input_expected = True
            self.update_display()
        except InvalidOperation:
            self.current_input = "Error"
            self.new_input_expected = True
            self.update_display()

    def clear_all(self):
        self.current_input = "0"
        self.history = ""
        self.previous_value = None
        self.pending_operator = None
        self.new_input_expected = False
        self.update_display()

    def clear_current(self):
        self.current_input = "0"
        self.update_display()

    def calculate_percentage(self):
        try:
            val = Decimal(self.current_input) / Decimal('100')
            self.current_input = self.format_decimal(val)
            self.update_display()
        except InvalidOperation:
            pass

    def toggle_sign(self):
        if self.current_input != "0" and self.current_input != "Error":
            if self.current_input.startswith('-'):
                self.current_input = self.current_input[1:]
            else:
                self.current_input = '-' + self.current_input
            self.update_display()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            self.input_number(chr(key))
        elif key == Qt.Key.Key_Period:
            self.input_decimal()
        elif key == Qt.Key.Key_Plus:
            self.input_operator('+')
        elif key == Qt.Key.Key_Minus:
            self.input_operator('-')
        elif key == Qt.Key.Key_Asterisk:
            self.input_operator('*')
        elif key == Qt.Key.Key_Slash:
            self.input_operator('/')
        elif key == Qt.Key.Key_Enter or key == Qt.Key.Key_Return or key == Qt.Key.Key_Equal:
            self.calculate()
        elif key == Qt.Key.Key_Backspace:
            if not self.new_input_expected and self.current_input != "0" and self.current_input != "Error":
                self.current_input = self.current_input[:-1]
                if not self.current_input or self.current_input == "-":
                    self.current_input = "0"
                self.update_display()
        elif key == Qt.Key.Key_Escape:
            self.clear_all()
        else:
            super().keyPressEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    calc = Calculator()
    calc.show()
    sys.exit(app.exec())