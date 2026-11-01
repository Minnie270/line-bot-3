def calculate_bmi(height_cm: float, weight_kg: float) -> float:
    height_m = height_cm / 100
    return weight_kg / (height_m ** 2)


def get_bmi_category(bmi: float) -> str:
    if bmi < 18.5:
        return "Underweight"
    elif bmi < 24.9:
        return "Normal weight"
    elif bmi < 29.9:
        return "Overweight"
    else:
        return "Obese"


def main():
    print("=== BMI Calculator ===")
    try:
        height = float(input("Enter your height in cm: "))
        weight = float(input("Enter your weight in kg: "))

        if height <= 0 or weight <= 0:
            print("Height and weight must be positive numbers.")
            return

        bmi = calculate_bmi(height, weight)
        category = get_bmi_category(bmi)

        print(f"\nYour BMI is: {bmi:.2f}")
        print(f"Category: {category}")
    except ValueError:
        print("Invalid input. Please enter numerical values.")


if __name__ == "__main__":
    main()

