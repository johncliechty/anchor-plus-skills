# -*- coding: utf-8 -*-
"""
Created on Wed Feb  9 13:53:26 2022

@author: jcl127

"""
from random import randrange
import random
import math
import time

overall_go = True
_go = True
sequenceCutNum = 5 # Max number of digits for remembering and repeating
secondsPause = 3

while overall_go:
    
    if _go == False:
        pType = int(input('To end type: 0'))
        if pType == 0:
            overall_go = False
        else:
            _go = True
            pType = int(input('Choose type of exercise to practice:\nAdd Sub 1D: 1\nAdd Sub 2D: 2\nMult 1D: 3\nMult 2D: 4\nFrac 1D: 5\nFrac 2D: 6\nsqrt 1D: 7\nMill Bill:8\n2^n: 9\nSequence:10\n          :'))
    else:
        pType = int(input('Choose type of exercise to practice:\nAdd Sub 1D: 1\nAdd Sub 2D: 2\nMult 1D: 3\nMult 2D: 4\nFrac 1D: 5\nFrac 2D: 6\nsqrt 1D: 7\nMill Bill:8\n2^n: 9\nSequence:10\n          :'))
    
    calc_str = "Calculate :"
    equal_str = "="
      
    UseMillBillFlag = False
      
    while _go:
      
        if pType == 1:
            num1 = randrange(10)
            while num1 == 0:
                num1 = randrange(10)            
            num2 = randrange(10)
            while num2 == 0:
                num2 = randrange(10)
            if random.random() < 0.5:
                tAns = num1 + num2
                strInput = calc_str + str(num1) + "+" + str(num2) + equal_str
            else:
                tAns = num1-num2
                strInput = calc_str + str(num1) + "-" + str(num2) + equal_str
        elif pType == 2:
            num1 = randrange(100)
            while num1 == 0:
                num1 = randrange(100)            
            num2 = randrange(100)
            while num2 == 0:
                num2 = randrange(100)
            if random.random() < 0.5:
                tAns = num1 + num2
                strInput = calc_str + str(num1) + "+" + str(num2) + equal_str
            else:
                tAns = num1-num2
                strInput = calc_str + str(num1) + "-" + str(num2) + equal_str      
        elif pType == 3:
            num1 = randrange(10)
            while num1 == 0:
                num1 = randrange(10)            
            num2 = randrange(10)
            while num2 == 0:
                num2 = randrange(10)
            tAns = num1 * num2
            strInput = calc_str + str(num1) + "x" + str(num2) + equal_str
        elif pType == 4:
            num1 = randrange(10)
            while num1 == 0:
                num1 = randrange(10)            
            num2 = randrange(100)
            while num2 == 0:
                num2 = randrange(100)
            tAns = num1 * num2
            strInput = calc_str + str(num1) + "x" + str(num2) + equal_str
        elif pType == 5:
            num1 = randrange(10)
            while num1 < 2:
                num1 = randrange(10) 
            tAns = 1 / num1
            strInput = calc_str + "1/" + str(num1) + equal_str
        elif pType == 6:
            num1 = randrange(100)
            while num1 == 0:
                num1 = randrange(100) 
            tAns = 1 / num1
            strInput = calc_str + "1/" + str(num1) + equal_str       
        elif pType == 7:
            num1 = randrange(10)
            while num1 == 0:
                num1 = randrange(10) 
            tAns = math.sqrt(num1)
            strInput = calc_str + "sqrt(" + str(num1) + ")" + equal_str
        elif pType == 8:
            UseMillBillFlag = True
            ThThFlag = False
            ThMilFlag = False
            MilMilFlag = False
            ThBilFlag = False
            num1 = randrange(10)
            while num1 == 0:
                num1 = randrange(10)            
            num2 = randrange(10)
            while num2 == 0:
                num2 = randrange(10)
            if random.random() < 0.333:
                num1 = num1*10
            elif random.random() < 0.5:
                num1 = num1*100
            if random.random() < 0.333:
                num2 = num2*10
            elif random.random() < 0.5:
                num2 = num2*100            
            if random.random() < 0.25:
                ThThFlag = True
                # Thousands by Thousands
                tAns = num1 * num2
                strInput = calc_str + str(num1) + " Thousand x " + str(num2) + " Thousand " + equal_str          
            elif random.random() < 0.333333:
                ThMilFlag = True
                tAns = num1 * num2
                strInput = calc_str + str(num1) + " Thousand x " + str(num2) + " Million " + equal_str          
            elif random.random() < 0.5:
                MilMilFlag = True
                tAns = num1 * num2
                strInput = calc_str + str(num1) +  " Million x " + str(num2) + " Million " + equal_str          
            else:
                ThBilFlag = True
                tAns = num1 * num2
                strInput = calc_str + str(num1) + " Thousand x " + str(num2) + " Billion " + equal_str     
        elif pType == 9:
            num1 = randrange(10)
            while num1 == 0:
                num1 = randrange(10) 
            num1 = num1+3
            tAns = pow(2,num1)
            strInput = calc_str + "2^" + str(num1) + equal_str
        elif pType == 10:
            num1 = randrange(10)
            while num1 < 3 or num1 > sequenceCutNum:
                num1 = randrange(10)
            num2 = pow(10,num1)
            while num2 == 0:
                num2 = pow(10,num1)
            num1 = randrange(num2)
            strInput = "Restate the random string:" + str(num1)
            tAns = num1
        
        if pType < 10:
            ans = float(input(strInput))
        else:
            print(strInput)
            time.sleep(secondsPause)
            ans = int(input("\n\n\n\n\n\n\n\n\n"))

    
        if pType == 8:
            ansMillBillTrill = int(input('1: Million, 2: Billion, 3: Trillion, 4: Qradrillion\n'))
            if ansMillBillTrill == 1:
                print('Million')
            elif ansMillBillTrill == 2:
                print('Billion')
            elif ansMillBillTrill == 3:
                print('Trillion')
            elif ansMillBillTrill == 4:
                print('Quadrillion')
                
            if ThThFlag:
                if tAns > 999:
                    tAnsMillBillTrill = 2
                else:
                    tAnsMillBillTrill = 1                
            if ThMilFlag:
                if tAns > 999:
                    tAnsMillBillTrill = 3
                else:
                    tAnsMillBillTrill = 2                
            if MilMilFlag:
                if tAns > 999:
                    tAnsMillBillTrill = 4
                else:
                    tAnsMillBillTrill = 3                 
            if ThBilFlag:
                if tAns > 999:
                    tAnsMillBillTrill = 4
                else:
                    tAnsMillBillTrill = 3      
    
            if tAns > 999:    
                if abs(ans-tAns/1000) < 0.001 and (ansMillBillTrill-tAnsMillBillTrill) == 0:
                    print('Good job')
                else:
                    if tAnsMillBillTrill == 1:
                        print('Miss, ',tAns/1000,' Million is the correct answer')  
                    elif tAnsMillBillTrill == 2:
                        print('Miss, ',tAns/1000,' Billion is the correct answer') 
                    elif tAnsMillBillTrill == 3:
                        print('Miss, ',tAns/1000,' Trillion is the correct answer')
                    elif tAnsMillBillTrill == 4:
                        print('Miss, ',tAns/1000,' Quadrillion is the correct answer')                      
            else:
                if abs(ans-tAns) < 0.001 and (ansMillBillTrill-tAnsMillBillTrill) == 0:
                    print('Good job')
                else:
                    if tAnsMillBillTrill == 1:
                        print('Miss, ',tAns,' Million is the correct answer')
                    elif tAnsMillBillTrill == 2:
                        print('Miss, ',tAns,' Billion is the correct answer') 
                    elif tAnsMillBillTrill == 3:
                        print('Miss, ',tAns,' Trillion is the correct answer')
                    elif tAnsMillBillTrill == 4:
                        print('Miss, ',tAns,' Quadrillion is the correct answer')              
        else:
            if abs(ans-tAns) < 0.001:
                print('Good job')
            else:
                print('Miss, ',tAns,' is the correct answer')
                    
        nb = input('Test: keep going = 1, stop anything else: ')
        if (nb != '1'):
            _go = False


    
    