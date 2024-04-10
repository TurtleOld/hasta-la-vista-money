import json

from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from hasta_la_vista_money.receipts.models import Receipt, Product
from hasta_la_vista_money.receipts.serializers import (
    ReceiptSerializer,
    CustomerSerializer,
)


class ReceiptListAPIView(ListCreateAPIView):
    authentication_classes = (TokenAuthentication,)
    serializer_class = ReceiptSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return Receipt.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = ReceiptSerializer(queryset, many=True)
        return Response(serializer.data)


class SellerListAPIView(ListCreateAPIView):
    authentication_classes = (TokenAuthentication,)
    serializer_class = ReceiptSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = 'id'

    def get_queryset(self):
        return Customer.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = CustomerSerializer(queryset, many=True)
        return Response(serializer.data)


class CustomerCreateAPIView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = CustomerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ReceiptCreateAPIView(ListCreateAPIView):
    def post(self, request, *args, **kwargs):
        request_data = json.loads(request.body)
        user_id = request_data.get('user')
        account_id = request_data.get('account')
        receipt_date = request_data.get('receipt_date')
        total_sum = request_data.get('total_sum')
        number_receipt = request_data.get('number_receipt')
        operation_type = request_data.get('operation_type')
        nds10 = request_data.get('nds10')
        nds20 = request_data.get('nds20')
        customer_data = request_data.get('customer')
        products_data = request_data.get('product')

        try:
            check_existing_receipt = Receipt.objects.filter(
                receipt_date=receipt_date,
                total_sum=total_sum,
            ).first()

            if not check_existing_receipt:
                user = User.objects.get(id=user_id)
                customer_data['user'] = user
                account = Account.objects.get(id=account_id)
                account.balance -= decimal.Decimal(total_sum)
                account.save()
                request_data['account'] = account
                customer = Customer.objects.create(**customer_data)
                receipt = Receipt.objects.create(
                    user=user,
                    account=account,
                    receipt_date=receipt_date,
                    customer=customer,
                    total_sum=total_sum,
                    number_receipt=number_receipt,
                    operation_type=operation_type,
                    nds10=nds10,
                    nds20=nds20,
                )

                for product_data in products_data:
                    # Удаляем receipt из product_data, чтобы избежать ошибки
                    product_data.pop('receipt', None)
                    product_data['user'] = user
                    # Создаем продукт
                    product = Product.objects.create(**product_data)
                    # Добавляем продукт к чеку
                    receipt.product.add(product)

                return Response(
                    ReceiptSerializer(receipt).data,
                    status=status.HTTP_201_CREATED,
                )
            return Response(
                'Такой чек уже был добавлен ранее',
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as error:
            return Response(
                str(error),
                status=status.HTTP_400_BAD_REQUEST,
            )
