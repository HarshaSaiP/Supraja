from django import forms

class GSTR1FilterForm(forms.Form):
    """Form to filter GSTR-1 data by month and year"""
    
    MONTH_CHOICES = [
        (1, 'January'),
        (2, 'February'),
        (3, 'March'),
        (4, 'April'),
        (5, 'May'),
        (6, 'June'),
        (7, 'July'),
        (8, 'August'),
        (9, 'September'),
        (10, 'October'),
        (11, 'November'),
        (12, 'December'),
    ]
    
    # Year choices (2026 to 2035)
    YEAR_CHOICES = [(year, year) for year in range(2026, 2036)]
    
    from_month = forms.ChoiceField(
        choices=MONTH_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='From Month'
    )
    from_year = forms.ChoiceField(
        choices=YEAR_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='From Year'
    )
    to_month = forms.ChoiceField(
        choices=MONTH_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='To Month'
    )
    to_year = forms.ChoiceField(
        choices=YEAR_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='To Year'
    )
